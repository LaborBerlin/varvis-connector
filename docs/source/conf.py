# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
from datetime import datetime

# Add the project source directory to the path so that autodoc can find the modules
sys.path.insert(0, os.path.abspath("../../src"))

# Import the package to get the version
import varvis_connector

# -- Project information -----------------------------------------------------
project = "varvis-connector"
copyright = f"{datetime.now().year}, Labor Berlin"
author = "Markus Konrad, Bernt Popp"
version = varvis_connector.__version__
release = version

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.apidoc",
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
]

templates_path = ["_templates"]
exclude_patterns = []

# -- Options for HTML output -------------------------------------------------
html_theme = "alabaster"
html_theme_options = {
    "page_width": "1100px",
    "show_related": True,
    "sidebar_collapse": False,
}
html_static_path = ["_static"]

# -- Extension configuration -------------------------------------------------
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_typehints_format = "short"

# -- Intersphinx mapping ----------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}
tls_verify = bool(int(os.getenv("VARVIS_SSL_VERIFY", "1")))
