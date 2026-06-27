"""Build AIOHTTP - override to use 3.9+ and skip C extensions for Python 3.14 compatibility"""
from pythonforandroid.recipe import PythonRecipe


class AIOHTTPRecipe(PythonRecipe):  # type: ignore # pylint: disable=R0903
    version = "3.9.5"
    url = "https://pypi.python.org/packages/source/a/aiohttp/aiohttp-{version}.tar.gz"
    name = "aiohttp"
    depends = ["setuptools"]
    call_hostpython_via_targetpython = False
    install_in_hostpython = True

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env['AIOHTTP_NO_EXTENSIONS'] = '1'
        env['LDFLAGS'] = env.get('LDFLAGS', '') + ' -lc++_shared'
        return env


recipe = AIOHTTPRecipe()
