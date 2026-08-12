# nfse-sefin

Cliente Python, licença MIT, para a API REST do Sistema Nacional NFS-e
(SEFIN Nacional / [gov.br/nfse](https://www.gov.br/nfse)).

O objetivo é ser integrável a qualquer sistema de gestão — petshop, clínica, salão,
ERP — com o mínimo de configuração possível.

```bash
pip install nfse-sefin
```

## O que a v0.1.0 faz

**Diagnóstico. Ainda não emite nota** — emissão é a v0.2.0, ver o roadmap em
[`DESIGN.md`](DESIGN.md).

Antes da primeira emissão, quatro coisas podem estar erradas, e nenhuma delas dá um
erro que explique a causa: o `.pfx` não abre, o certificado venceu, o handshake mTLS
não fecha, ou o município nunca aderiu ao Sistema Nacional. O `nfse-doctor` responde as
quatro de uma vez.

```console
$ nfse-doctor --pfx empresa.pfx --municipio 3304557 --servico "banho e tosa"
nfse-doctor 0.1.0 — ambiente: producao_restrita

  [OK  ] certificado aberto: PETSHOP EXEMPLO LTDA:12345678000195
  [OK  ] certificado válido por mais 214 dias
  [OK  ] handshake mTLS fechou
  [OK  ] município 3304557 aderiu ao Sistema Nacional
  [OK  ] rota de convênio que respondeu: .../parametrizacao/3304557/convenio
  [OK  ] 1 serviço(s) para 'banho e tosa':
         cTribNac 060301  Banhos, duchas, sauna, massagens e congêneres.

Tudo pronto para emitir.
```

A senha vem do prompt por padrão. `--senha` existe mas fica no histórico do shell e
aparece em `ps`; prefira `NFSE_PFX_SENHA` se precisar automatizar.

O código de saída é distinto por causa, para script de implantação decidir sem parsear
texto: `0` sucesso, `3` PKCS#12 ilegível, `4` certificado inválido, `5` mTLS recusado,
`6` município não aderente, `7` argumento inválido.

## Como biblioteca

```python
from nfse_sefin import Ambiente, Certificate, bases_de
from nfse_sefin.catalogos import buscar_servico, por_codigo

cert = Certificate.from_pfx("empresa.pfx", password="senha")
print(cert.cn, cert.dias_para_vencer, cert.precisa_renovar)

# As quatro bases do Sistema Nacional. Não são intercambiáveis:
# POST /nfse no ADN não emite nota, e o DANFSe não fica no SEFIN.
bases = bases_de(Ambiente.PRODUCAO_RESTRITA)

# A lista nacional de serviços, com busca por texto ou por qualquer
# das três grafias que os documentos oficiais usam.
buscar_servico("banho")        # -> cTribNac 060301
por_codigo("10101")            # -> 010101, com o zero que o Excel comeu
por_codigo("01.01.01")         # -> o mesmo
```

## Certificado

Certificado ICP-Brasil **A1** (arquivo `.pfx`/`.p12`), autenticação mTLS. A3 (token,
smartcard) é não-objetivo declarado da v1.

Nenhum endpoint do Sistema Nacional responde sem certificado cliente — nem o Swagger de
produção restrita.

## Design

- [DESIGN.md](DESIGN.md) — arquitetura, premissas, perguntas abertas e roadmap. Fonte
  única das decisões do projeto. Leia antes de propor mudança estrutural.

## Desenvolvimento

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy nfse_sefin tests tools
```

`tests/test_nfelib_contract.py` é o alarme da dependência de forma com a
[`nfelib`](https://github.com/akretion/nfelib): esta biblioteca usa os bindings que ela
gera com `xsdata` a partir dos XSD oficiais, em vez de escrever os 416 campos do leiaute
à mão. Se o upstream renomear um campo ou publicar esquema novo, o teste falha alto em
vez de o mapeamento quebrar em silêncio.

`nfse_sefin/catalogos/servicos.py` é **gerado** por `tools/gerar_catalogo_servicos.py`.
Não edite à mão: o CI confere que o arquivo versionado é exatamente o que sai do anexo
versionado.

## Esquemas oficiais

`Schemas/` traz os XSD oficiais do `nfse-esquemas_xsd-v1-01-20260209.zip`, copiados sem
alteração. Procedência, SHA-256 e a razão de estarem versionados aqui:
[`Schemas/PROCEDENCIA.md`](Schemas/PROCEDENCIA.md).

As duas versões de leiaute estão vivas em paralelo (`TVerNFSe` aceita `1.00|1.01`), e o
`xmldsig-core-schema.xsd` difere entre elas — o que decide como a assinatura é montada.

`.github/workflows/watch-upstream.yml` abre issue quando o gov.br publica um ZIP com data
nova, ou quando um release novo da `nfelib` quebra a suíte de contrato.

## Documentação oficial de referência

- [manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e-v1-2-out2025.md](manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e-v1-2-out2025.md)
- [anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md](anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md)
- [anexo_ii-sefin_adn-pedregevt_evt-snnfse-v1-01-20260122.md](anexo_ii-sefin_adn-pedregevt_evt-snnfse-v1-01-20260122.md)
- [manual-contribuintes-apis-adn-sistema-nacional-nfse.md](manual-contribuintes-apis-adn-sistema-nacional-nfse.md)

## Licença

MIT — ver [LICENSE](LICENSE). Os arquivos em `Schemas/` são de autoria da SEFIN Nacional
e não estão cobertos por essa licença.
