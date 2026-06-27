"""Build pyjnius - local recipe override for Android cross-compilation"""
import os
from os.path import exists, join
from pythonforandroid.recipe import CythonRecipe


class JniusRecipe(CythonRecipe):
    version = "1.7.0"
    url = "https://github.com/kivy/pyjnius/archive/refs/tags/{version}.tar.gz"
    name = "jnius"
    depends = ["six", "setuptools"]
    call_hostpython_via_targetpython = False
    install_in_hostpython = True

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        # Locate JDK in the buildozer Docker image
        for jdk_candidate in [
            "/usr/lib/jvm/java-17-openjdk-amd64",
            "/usr/lib/jvm/java-11-openjdk-amd64",
            "/usr/lib/jvm/java-1.17.0-openjdk-amd64",
            "/usr/lib/jvm/java-1.11.0-openjdk-amd64",
            "/usr/lib/jvm/default-java",
        ]:
            if exists(jdk_candidate):
                env["JAVA_HOME"] = jdk_candidate
                break
        # Add NDK platform path for jni.h
        ndk_dir = os.environ.get("NDK_DIR", "")
        if ndk_dir and exists(ndk_dir):
            sysroot = join(
                ndk_dir,
                "toolchains",
                "llvm",
                "prebuilt",
                "linux-x86_64",
                "sysroot",
            )
            if exists(sysroot):
                cflags = env.get("CFLAGS", "")
                env["CFLAGS"] = f"{cflags} -I{sysroot}/usr/include"
        return env


recipe = JniusRecipe()