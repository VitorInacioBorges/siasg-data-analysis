# siasg-data-analysis

analysis of all brazilian goverment transactions. It studies how often expenses are made and for what purpose using machine learning and data analysis

### Basic Setup: (Ubuntu/Linux)

```bash

# update and dependency installation
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv python3-dev -y

# creates the runtime environment (venv folder)
python3 -m venv venv

# activates runtime environment for this project on Linux/WSL (using terminal activation from venv folder)
# for terminal usage has to run everytime
source venv/bin/activate

# deactivates python runtime environment
deactivate

# AI & ML dependencies (python inside module for this project)
python -m pip install numpy pandas matplotlib scikit-learn tensorflow torch seaborn

# AI & ML dependencies (pip only)
pip install numpy pandas matplotlib scikit-learn tensorflow torch seaborn

# AI & ML dependencies (pip inside venv)
venv/bin/python -m pip install numpy pandas matplotlib scikit-learn tensorflow torch seaborn requests tqdm python-dotenv

# To view all packages installed from terminal
cd venv/bin/python3.14/site-packages
ls

# GUI installation for Matplotlib
venv/bin/python -m pip install pyqt5 # PyQt => Cross-platform
sudo apt-get install python3-tk # Tkinter => Linux/Ubuntu

# debugging and checking if pip and python match the same folder
# if not then change pip or python
which python
which pip
```
