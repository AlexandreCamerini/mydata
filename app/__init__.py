"""Portal de Dados — API de dados de empresas listadas na B3.

Camadas: bronze (arquivo oficial, imutável) → silver (tipado) → campos
calculados (catálogo declarativo) → gold (views publicadas).
Ver docs/arquitetura.md.
"""

__version__ = "0.1.0"
