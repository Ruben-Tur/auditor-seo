"""rastreo: auditor de SEO técnico que recorre una web y genera un informe priorizado."""

__version__ = "0.1.0"

AUTOR = "Rubén Tur"
URL_AUTOR = "https://github.com/Ruben-Tur"

# Un User-Agent identificable permite al dueño de la web saber quién le rastrea
# y bloquearnos desde su robots.txt si lo prefiere.
USER_AGENT = f"rastreo/{__version__} (+https://github.com/Ruben-Tur/auditor-seo)"
