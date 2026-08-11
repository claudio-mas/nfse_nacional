"""Cliente Python para a API REST do Sistema Nacional NFS-e (SEFIN Nacional).

Esqueleto. Os módulos públicos entram na ordem definida em `DESIGN.md`,
seção "Ordem de release":

- v0.1.0 — `ambientes`, `cert`, `transport`, `errors`, `convenio`,
  `catalogos.servicos`, `doctor`. Diagnóstico; não emite nota.
- v0.2.0 — `perfis`, `signing`, `catalogos.rejeicoes`, `facade`, `adapters`,
  emissão, consulta e DANFSe.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0.dev0"
