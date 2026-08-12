# nfse_sefin

Cliente Python, licença MIT, para a API REST do Sistema Nacional NFS-e
(SEFIN Nacional / [gov.br/nfse](https://www.gov.br/nfse)).

O objetivo é ser integrável a qualquer sistema de gestão — petshop, clínica, salão,
ERP — com o mínimo de configuração possível.

> **Estado: esqueleto.** Ainda não emite nota e ainda não está publicado no PyPI.
> A ordem de release está em [`DESIGN.md`](DESIGN.md), seção "Ordem de release":
> `v0.1.0` é diagnóstico, `v0.2.0` é emissão.

## Design

- [DESIGN.md](DESIGN.md) — arquitetura, premissas e roadmap. Fonte única das decisões
  do projeto. Leia antes de propor mudança estrutural.

## Desenvolvimento

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy nfse_sefin tests
```

`tests/test_nfelib_contract.py` é o alarme da dependência de forma com a
[`nfelib`](https://github.com/akretion/nfelib): esta biblioteca usa os bindings que
ela gera com `xsdata` a partir dos XSD oficiais, em vez de escrever os 416 campos do
leiaute à mão. Se o upstream renomear um campo ou publicar esquema novo, o teste
falha alto em vez de o mapeamento quebrar em silêncio.

## Esquemas oficiais

`Schemas/` traz os XSD oficiais do `nfse-esquemas_xsd-v1-01-20260209.zip`, copiados
sem alteração. Procedência, SHA-256 e a razão de estarem versionados aqui:
[`Schemas/PROCEDENCIA.md`](Schemas/PROCEDENCIA.md).

As duas versões de leiaute estão vivas em paralelo (`TVerNFSe` aceita `1.00|1.01`), e
o `xmldsig-core-schema.xsd` difere entre elas — o que decide como a assinatura é
montada. Ver a seção "Assinatura" do `DESIGN.md`.

`.github/workflows/watch-upstream.yml` abre issue quando o gov.br publica um ZIP com
data nova, ou quando um release novo da `nfelib` quebra a suíte de contrato.

## Documentação oficial de referência

- [manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e-v1-2-out2025.md](manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e-v1-2-out2025.md)
- [anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md](anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md)
- [anexo_ii-sefin_adn-pedregevt_evt-snnfse-v1-01-20260122.md](anexo_ii-sefin_adn-pedregevt_evt-snnfse-v1-01-20260122.md)
- [manual-contribuintes-apis-adn-sistema-nacional-nfse.md](manual-contribuintes-apis-adn-sistema-nacional-nfse.md)

## Licença

MIT — ver [LICENSE](LICENSE). Os arquivos em `Schemas/` são de autoria da SEFIN
Nacional e não estão cobertos por essa licença.

## Observações

- Os arquivos com sufixo `:Zone.Identifier` são metadados do Windows e não fazem
  parte do conteúdo principal.
