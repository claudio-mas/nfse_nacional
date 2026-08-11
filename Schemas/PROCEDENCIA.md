# Procedência dos esquemas XSD

Estes arquivos **não** são de autoria deste projeto. São os esquemas oficiais do
Sistema Nacional NFS-e, publicados pela SEFIN Nacional, copiados sem alteração.

| campo | valor |
|---|---|
| Arquivo de origem | `nfse-esquemas_xsd-v1-01-20260209.zip` |
| Origem | https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual |
| SHA-256 do ZIP | `e7935cbd9470527c6cc32984c1b2263e614183bf0139ce2733eaaed2de9a8072` |
| Baixado em | 2026-08-11 |

## Por que estão versionados aqui

Os testes validam o XML gerado contra os XSD oficiais. Depender de download em
tempo de teste tornaria a suíte dependente de rede e do WAF do gov.br, que recusa
clientes não-browser com HTTP 403.

## Não use a cópia da nfelib no lugar destes

A `nfelib` 2.5.2 embarca uma cópia dos esquemas 1.00, mas ela está **atrás** do
ZIP oficial atual e não cobre a 1.01:

| arquivo | nfelib 2.5.2 | ZIP oficial 20260209 |
|---|---|---|
| `tiposComplexos_v1.00.xsd` | 78.115 bytes | 80.390 bytes |
| `tiposSimples_v1.00.xsd` | 57.965 bytes | 59.136 bytes |
| `CNC_v1.00.xsd`, `tiposCnc_v1.00.xsd` | ausentes | presentes |
| `Schemas/1.01/` | ausente | 10 arquivos |

## As duas versões estão vivas

`tiposSimples_v1.01.xsd` documenta `TVerNFSe` como `1.00|1.01`, e o
`targetNamespace` é idêntico nas duas. A 1.01 acrescenta a camada IBS/CBS da
reforma tributária, contida em um único arquivo (`tiposComplexos_v1.01.xsd`,
30 ocorrências de `IBSCBS`; zero em toda a 1.00).

O `xmldsig-core-schema.xsd` **difere entre as duas versões** e isso decide a
assinatura. Ver a seção "Assinatura" do `DESIGN.md`.

## Como atualizar

O workflow `.github/workflows/watch-upstream.yml` falha quando o gov.br publica um
ZIP com data diferente. Quando isso acontecer: baixe o novo, substitua `Schemas/`,
atualize este arquivo, e rode a suíte.
