from os import makedirs
from os.path import dirname, join as joinpath, abspath
from shutil import copyfile, make_archive
from zipapp import create_archive
from zipfile import ZipFile

NAME = 'ProtocolProxy.pyzw'

src = dirname(abspath(__file__))
dest = joinpath(src, 'dist_zip')

files = (
    r"__main__.py",
    r"app.py",
    r"device.py",
    r"entry.py",
    r"notifier.py",
    r"ui.py",
    r"res/__init__.py",
    r"res/icon_r.png",
)

try:
    makedirs(joinpath(dest, 'res'), exist_ok=True)
    for file in files:
        copyfile(joinpath(src, file), joinpath(dest, file))
    create_archive(dest, joinpath(src, NAME))
except Exception as e:
    print(f"{e.__class__.__name__}: {e}")
else:
    print('DONE')


# try:
#     arc = ZipFile(dest, 'w')
#     for file in files:
#         arc.write(joinpath(src, file))
# except Exception as e:
#     print(f"{e.__class__.__name__}: {e}")
# else:
#     print('DONE')