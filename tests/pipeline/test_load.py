import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.load import load_raw

HEADER = ("idCompraItem,dataInclusaoPncp,codigoClasse,materialOuServicoNome,"
             "situacaoCompraItemNome,itemCategoriaNome,temResultado,codigoGrupo,"
             "quantidade,valorUnitarioEstimado,valorTotal,valorTotalResultado\n")


def _row(ident, classe="7010.0", status="Homologado", qtd="10"):
    return (f"{ident},2025-09-22T00:04:59,{classe},Material,{status},"
            f"Informática (TIC),True,,{qtd},100.0,1000.0,900.0\n")


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "raw" / "contract_items.csv"
    path.parent.mkdir(parents=True)
    path.write_text(
        HEADER
        + _row("a1", qtd="10")
        # Mesma chave, quantidade diferente. Deliberado: se as duas linhas
        # fossem idênticas, um drop_duplicates() SEM subset passaria no teste
        # igualmente, e o teste não provaria nada sobre a chave.
        + _row("a1", qtd="99")
        + _row("a2")
        + _row("a3", status="Fracassado")     # filtrada pelo status
        , encoding="utf-8-sig")
    return PipelineSettings(
        raw_csv=path, interim_dir=tmp_path / "interim",
        processed_dir=tmp_path / "processed", figures_dir=tmp_path / "fig",
        read_chunk_rows=2)


def test_drops_duplicate_ids(cfg):
    """A deduplicação é pela CHAVE, não pela linha inteira.

    As duas linhas "a1" do fixture diferem em `quantidade`, então um
    `drop_duplicates()` sem subset deixaria as duas e este teste falharia. É o
    caso real: 23,4% do arquivo são re-downloads de um bloco interrompido, e
    nada garante que o valor de um item não mudou entre as tentativas.
    """
    df = load_raw(cfg.raw_csv, cfg)
    assert df["idCompraItem"].is_unique
    assert set(df["idCompraItem"]) == {"a1", "a2"}
    # keep="first": a linha mantida é a primeira que apareceu no arquivo
    mantida = df[df["idCompraItem"] == "a1"]["quantidade"].iloc[0]
    assert mantida == 10.0, "esperava a primeira ocorrência, não a segunda"


def test_drops_the_three_dead_columns(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    for morta in ("itemCategoriaNome", "temResultado", "codigoGrupo"):
        assert morta not in df.columns


def test_filters_by_status(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    assert (df["situacaoCompraItemNome"] == "Homologado").all()


def test_types_and_normalisation(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    assert df["quantidade"].dtype == "float64"
    assert pd.api.types.is_datetime64_any_dtype(df["dataInclusaoPncp"])
    # o CSV traz "7010.0"; o código é identificador, não número
    assert df["codigoClasse"].iloc[0] == "7010"


def _cfg_for(path):
    return PipelineSettings(
        raw_csv=path, interim_dir=path.parent / "i",
        processed_dir=path.parent / "p", figures_dir=path.parent / "f")


def test_reports_skipped_lines(tmp_path, capsys):
    """Uma linha com campo SOBRANDO é pulada pelo pandas — e o aviso conta.

    Medido no pandas 3.0.5: on_bad_lines="skip" descarta a linha que tem campos
    a mais, e só essa. Campo faltando é preenchido com NaN e mantido — por isso
    truncamento tem detecção própria, nos dois testes seguintes.
    """
    path = tmp_path / "contract_items.csv"
    path.write_text(
        HEADER
        + _row("b1")
        + _row("b2").rstrip("\n") + ",campo,a,mais\n"   # campos sobrando
        + _row("b3"),
        encoding="utf-8-sig")

    df = load_raw(path, _cfg_for(path))

    assert set(df["idCompraItem"]) == {"b1", "b3"}
    out = capsys.readouterr().out
    assert "puladas" in out
    assert "1 linha" in out


def test_drops_a_partial_last_row(tmp_path, capsys):
    """A linha pela metade é descartada, não apenas contada.

    É a forma que o coletor produz ao ser morto no meio de uma gravação: sem
    newline final, campos faltando. O pandas a preencheria com NaN e a
    manteria; com o id intacto ela sobreviveria à deduplicação, somaria zero em
    tudo e subestimaria o painel em silêncio.
    """
    path = tmp_path / "contract_items.csv"
    path.write_text(
        HEADER
        + _row("c1")
        + "c2,2025-09-22T00:04:59,7010,Mat",   # cortada no meio, sem newline
        encoding="utf-8-sig")

    df = load_raw(path, _cfg_for(path))

    assert set(df["idCompraItem"]) == {"c1"}
    assert "pela metade" in capsys.readouterr().out


def test_file_changing_mid_read_discards_nothing(tmp_path, capsys, monkeypatch):
    """Se o arquivo muda durante a leitura, nenhuma linha é descartada.

    O motivo de existir: a foto de "termina no meio de uma linha" é tirada
    antes do parse. Se o coletor completa a escrita nesse intervalo, o sinal
    fica velho e o descarte joga fora uma linha legítima. Checar depois do
    parse não resolve — só move a janela para o erro simétrico.
    """
    from pipeline import load as modulo

    path = tmp_path / "contract_items.csv"
    # A linha parcial é cortada DEPOIS da coluna de situação, senão o filtro de
    # status a removeria por conta própria e o teste não provaria nada.
    parcial = ("e2,2025-09-22T00:04:59,7010,Material,Homologado,"
               "Informática (TIC),True,,10,100.0")
    path.write_text(HEADER + _row("e1") + parcial, encoding="utf-8-sig")

    fotos = iter([(1, 1), (2, 2)])          # duas fotos diferentes = mudou
    monkeypatch.setattr(modulo, "_snapshot", lambda _: next(fotos))

    df = load_raw(path, _cfg_for(path))

    out = capsys.readouterr().out
    assert "mudou durante a leitura" in out
    assert "nenhuma linha foi descartada" in out
    # a parcial continua ali: o sinal que mandaria descartá-la era velho
    assert set(df["idCompraItem"]) == {"e1", "e2"}


def test_truncation_inside_a_quoted_field_gives_a_clear_error(tmp_path):
    """on_bad_lines não pega este caso: o pandas levanta ParserError.

    Sem tratamento, load_raw morre com um traceback do tokenizador que não diz
    nada a quem roda. A mensagem tem de nomear a causa e o que fazer.
    """
    path = tmp_path / "contract_items.csv"
    path.write_text(
        HEADER + _row("d1") + 'd2,2025-09-22T00:04:59,"classe sem fecho',
        encoding="utf-8-sig")

    with pytest.raises(RuntimeError, match="RESUME=true"):
        load_raw(path, _cfg_for(path))


def test_no_message_when_nothing_is_skipped(cfg, capsys):
    """O caminho silencioso também precisa ser afirmado, não só acontecer."""
    load_raw(cfg.raw_csv, cfg)
    assert "puladas" not in capsys.readouterr().out


def test_missing_file_gives_a_clear_message(cfg, tmp_path):
    with pytest.raises(FileNotFoundError, match="src/main.py"):
        load_raw(tmp_path / "nao-existe.csv", cfg)
