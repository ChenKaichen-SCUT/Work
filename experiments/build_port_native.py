"""Build optional Linux/GCC port algebra accelerator for the running CPython."""
import subprocess,sysconfig
from pathlib import Path
root=Path(__file__).resolve().parents[1]
output=root/'wmcheck'/('_port_native'+sysconfig.get_config_var('EXT_SUFFIX'))
subprocess.run(['g++','-O3','-std=c++17','-shared','-fPIC',
    '-I'+sysconfig.get_paths()['include'],str(root/'wmcheck/port_native.cpp'),'-o',str(output)],check=True)
print(output)
