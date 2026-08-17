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

## Emitir uma nota

Em desenvolvimento na v0.2.0, e o caminho completo já funciona: montar, validar,
assinar, enviar, consultar e baixar o DANFSe.

O leiaute chama o código do serviço de `dps.infDPS.serv.cServ.cTribNac`. Ninguém
deveria precisar saber disso:

```python
from datetime import date
from decimal import Decimal

from nfse_sefin import DPS, OpcaoSimplesNacional, Prestador, Servico

dps = DPS(
    prestador=Prestador(
        cnpj="01.761.135/0001-32",                  # pontuação e DV conferidos aqui
        inscricao_municipal="12345",
        simples_nacional=OpcaoSimplesNacional.MEI,
    ),
    servico=Servico(
        codigo="060301",                            # cTribNac, e ele tem de existir
        descricao="Banho e tosa",
        valor=Decimal("150.00"),                    # Decimal, nunca float
        municipio_prestacao="3304557",              # código IBGE, não o nome
    ),
    serie="1",
    numero="42",                                    # o contador é do seu ERP
    competencia=date(2026, 8, 17),
    municipio_emissor="3304557",
)

dps.identificador   # DPS330455720176113500013200001000000000000042 — as 45 posições
```

O que isso já poupa, tudo antes de gastar uma conexão:

- **O identificador de 45 posições**, montado na ordem que `E0004` exige — com
  `serie` zerada à esquerda no `Id` e não no elemento, e CPF completado com `000`.
- **`dhEmi` sem microssegundo.** `datetime.now(tz).isoformat()` produz um valor que o
  XSD recusa, e a rejeição não diz por quê.
- **O grupo `totTrib`.** É obrigatório, é um `xs:choice` de quatro, e qual dos quatro
  é permitido depende do Simples Nacional do prestador — regra que está no Anexo I
  como `E0710`, `E0712` e `E0713`, não no schema. MEI tem padrão; os outros regimes
  falham com a instrução de qual construtor usar.
- **Dígito verificador** de CPF e CNPJ, código IBGE de 7 dígitos, CEP de 8,
  `cIntContrib` sem hífen, alíquota dentro do teto de um dígito do `pAliq`.
- **Caracteres que o `TSString` recusa** — travessão e aspas curvas coladas de um
  editor de texto passam despercebidos até a recepção rejeitar.

Com a DPS pronta, o cliente cuida do resto:

```python
from pathlib import Path

from nfse_sefin import Ambiente, Certificate, NFSeClient
from nfse_sefin.errors import MunicipioNaoAderente, RejeicaoNFSe

cert = Certificate.from_pfx("empresa.pfx", password="senha")

with NFSeClient(cert, ambiente=Ambiente.PRODUCAO_RESTRITA) as cliente:
    if not cliente.consultar_convenio("3304557").aderido:   # passo zero
        raise MunicipioNaoAderente("3304557")

    try:
        nota = cliente.emitir(dps)          # assina, comprime, envia
    except RejeicaoNFSe as erro:
        print(erro)                         # "E0014: ... já existe em uma NFS-e"
        print(erro.caminhos_xml)            # ('NFSe/infNFSe/DPS/infDPS/serie',)
        raise

    pdf = cliente.baixar_danfse(nota.chave_acesso)
    Path("nota.pdf").write_bytes(pdf)
    Path("nota.xml").write_bytes(nota.xml)  # já descomprimido, pronto para arquivar
```

Três decisões que o cliente toma por você:

- **O `tpAmb` é do cliente, não da DPS.** `emitir` sobrescreve o campo a partir do
  `Ambiente` configurado, com aviso no log quando o valor era outro. Uma DPS montada
  para produção restrita e enviada para produção seria emissão real marcada como
  teste.
- **`POST /nfse` nunca repete.** Escrita fiscal não é idempotente: repetir depois de
  o servidor ter processado emite a mesma nota duas vezes. Quando a conexão cai sem
  resposta, a exceção carrega o identificador da DPS e manda consultar em vez de
  reenviar:

  ```python
  if cliente.dps_foi_processada(dps.identificador):
      chave = cliente.chave_por_dps(dps.identificador)
  ```
- **Rejeição não é erro de transporte.** `E0014` vira `RejeicaoNFSe` com o texto
  oficial da regra e o caminho XML do campo culpado; um 502 de proxy continua sendo
  `TransporteError`. A diferença é o que dá para fazer a seguir — transporte às vezes
  passa na próxima tentativa, rejeição devolve o mesmo erro sempre.

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
