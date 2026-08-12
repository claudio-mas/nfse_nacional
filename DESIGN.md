# Design: nfse-sefin — biblioteca Python MIT para o Sistema Nacional NFS-e

Revisão 3.1 — aprovada em 2026-08-11.
Sessão de resolução de gates: OQ1, OQ2, OQ3, OQ4, OQ6 e OQ7 fechados com dado verificado.

## Problem Statement

Construir uma biblioteca Python reutilizável, licença MIT, para integração com a API
REST oficial do Sistema Nacional NFS-e (SEFIN Nacional / gov.br/nfse), instalável via
`pip` e integrável a qualquer sistema de gestão (petshop, clínica, salão, ERP) com o
mínimo de configuração possível.

A frase que define o projeto, nas palavras do autor:

> "A biblioteca deve poder ser integrada a qualquer sistema de gestão (petshop, clínica,
> salão, ERP etc.) com o mínimo de configuração possível."

Todo o resto do design se subordina a ela.

## O que mudou na revisão 3

A revisão 2 terminou com doze perguntas abertas, duas delas classificadas como gates que
bloqueavam qualquer linha de código. Esta sessão foi atrás dos dados. Seis fecharam, uma
premissa central caiu, e apareceu um erro de arquitetura que teria quebrado toda emissão.

| Item | Status na rev. 2 | Status agora |
|---|---|---|
| OQ1 — `nfelib` no esquema v1.00 vs. anexos v1.01 | GATE, bloqueia código | **Rebaixado.** As duas versões estão vivas em paralelo |
| OQ2 — algoritmo de compressão | GATE, bloqueia código | **Resolvido: gzip** |
| OQ3 — envelope de request/response | Aberto | **Resolvido**, com contrato completo mapeado |
| OQ4 — algoritmo de assinatura | Aberto, "o XSD talvez não responda" | **Resolvido**, e o XSD responde diferente por versão |
| OQ6 — convênio funciona sem certificado? | Aberto | **Resolvido: não.** Nada responde sem certificado cliente |
| OQ7 — DANFSe sem spec de leiaute | v0.4.0 contingente | **Resolvido:** existe `GET /danfse/{chave}` |
| — | — | **NOVO: a URL base do design estava errada** |

## Erro corrigido: SEFIN e ADN são dois sistemas, não um

A revisão 2 (e o plano original) definiam um único par de URLs base:

```python
# ERRADO — isto manda a emissão para o sistema de consulta
AMBIENTES = {
    "producao_restrita": "https://adn.producaorestrita.nfse.gov.br/contribuintes",
    "producao":          "https://adn.nfse.gov.br/contribuintes",
}
```

São **quatro** bases com papéis distintos. Confirmado de forma independente em
`brans-nfe/client.py` e `pynfse-nacional/constants.py`, e coerente com o manual do ADN
publicado em 12/02/2026:

| Papel | Produção | Produção restrita |
|---|---|---|
| **SEFIN** — emitir, consultar NFS-e, `/dps/{id}`, eventos | `https://sefin.nfse.gov.br/SefinNacional` | `https://sefin.producaorestrita.nfse.gov.br/SefinNacional` |
| **ADN raiz** — DANFSe `GET /danfse/{chave}` | `https://adn.nfse.gov.br` | `https://adn.producaorestrita.nfse.gov.br` |
| **ADN parametrização** — convênio municipal, alíquotas | `https://adn.nfse.gov.br/parametrizacao` | `https://adn.producaorestrita.nfse.gov.br/parametrizacao` |
| **ADN contribuintes** — distribuição `GET /DFe/{NSU}`, eventos por chave | `https://adn.nfse.gov.br/contribuintes` | `https://adn.producaorestrita.nfse.gov.br/contribuintes` |

O ADN é o Ambiente de Dados Nacional: compartilhamento e consulta. Quem gera NFS-e é a
SEFIN. `POST /nfse` no ADN não emite nota nenhuma.

Nota adicional: a rota do convênio é `{ADN}/parametrizacao/{codMun}/convenio`, não
`/contribuintes/parametros_municipais/{codMun}/convenio` como a revisão 2 registrava.

Segunda nota, corrigida após a revisão 3: o DANFSe **não** fica no SEFIN. As duas libs
concorrentes montam a URL na raiz do ADN, sem prefixo de caminho — `brans-nfe/client.py:239`
usa `f"{self.adn_url}/danfse/{chave_acesso}"` com `adn_url` sendo o host nu, e
`pynfse-nacional/client.py:1269` troca `sefin.` por `adn.` no host antes de concatenar
`/danfse/{chave}`. São quatro bases, não três.

## What Makes This Cool

Três coisas, em ordem de força. A primeira mudou de natureza nesta revisão e ficou mais forte.

**1. O `doctor` que descobre o par que funciona.** A revisão 2 justificava o `doctor` como
diagnóstico de município e certificado. Isso continua valendo, mas apareceu um trabalho que
só ele pode fazer: **ninguém sabe qual combinação de versão de leiaute e algoritmo de
assinatura o servidor aceita hoje.** As duas bibliotecas concorrentes escolheram combinações
opostas em todos os eixos e as duas afirmam funcionar. Um comando que emite uma DPS de teste
em produção restrita nos dois formatos e responde "o servidor aceitou 1.01+SHA256, rejeitou
1.00+SHA1 com E####" resolve empiricamente uma pergunta que a documentação oficial não
responde. Isso é o oposto de mais um wrapper de XML.

**2. A fachada sobre `nfelib`.** Os bindings gerados preservam os nomes do XSD. O caminho
real para o código de serviço é `dps.infDPS.serv.cServ.cTribNac`. Um dev de petshop não
deveria precisar saber disso. A fachada é a única coisa que as libs MIT concorrentes não
têm — e é exatamente a promessa do projeto.

**3. A tradução de rejeição.** A SEFIN devolve `E0014` e o dev vai caçar. Os anexos oficiais
têm 429 regras com código `E####` e o texto de cada uma. Transformar `E0014` numa exceção
tipada que carrega o código, o texto literal do anexo e — quando o anexo fornece — o
caminho XML culpado transforma horas de caça em segundos.

## Verificação executada nesta sessão

Tudo abaixo foi rodado, não inferido.

### Transporte (fecha OQ2 e OQ3)

Três implementações independentes concordam no formato do payload:

```python
# brans-nfe/signer.py:52
base64.b64encode(gzip.compress(xml_bytes)).decode("ascii")
# pynfse-nacional/xml_signer.py:158
compressed = gzip.compress(data.encode("utf-8"))
# nfse-nacional/api_client.py:94
xml_gzip = gzip.compress(xml_bytes)
```

É **gzip** — não raw deflate, não zlib. A revisão 2 tinha razão em rebaixar "GZip" a
pergunta aberta (a palavra não aparece em nenhum documento oficial), e a resposta empírica
confirma o palpite do plano original.

Contrato de request e response, mapeado campo a campo:

| Operação | Request | Response 2xx |
|---|---|---|
| `POST {SEFIN}/nfse` | `{"dpsXmlGZipB64": "<gzip+b64>"}` | `{"chaveAcesso", "idDps", "tipoAmbiente", "versaoAplicativo", "dataHoraProcessamento", "nfseXmlGZipB64", "alertas"}` |
| `POST {SEFIN}/nfse/{chave}/eventos` | `{"pedidoRegistroEventoXmlGZipB64": "..."}` | `{"retEvento": {"cStat": 144, "xMotivo", "idEvento"}}` |
| `GET {SEFIN}/dps/{id}` | — | `{"chaveAcesso", "idDps", "tipoAmbiente", ...}` |
| `HEAD {SEFIN}/dps/{id}` | — | 200 existe / 404 não existe |
| `GET {ADN}/danfse/{chave}` | — | PDF binário |
| `GET {ADN}/contribuintes/DFe/{NSU}` | — | `{"ArquivoXml"/"arquivoXml": "<gzip+b64>"}` |

`Content-Type: application/json`. Os campos de XML sempre vêm gzip+base64 nos dois sentidos.

Duas descobertas de contrato que valem código defensivo:

- **A forma do erro não é estável.** `pynfse-nacional` normaliza **quatro** formatos
  diferentes vistos em produção: `{"erro": [{codigo, descricao, complemento}]}`,
  `{"erros": [...]}`, uma lista nua no topo, e o legado `{"codigo", "mensagem"}`. Um parser
  que assume uma única forma quebra. `errors.py` tem que normalizar as quatro.
- **Eventos falam outro idioma.** A resposta de evento usa o padrão `cStat`/`xMotivo`
  herdado da SEFAZ (`cStat: 144` = evento recebido), enquanto a resposta de DPS usa
  `chaveAcesso`/`erro`. São dois contratos distintos dentro da mesma API.

### Assinatura (fecha OQ4)

A revisão 2 supunha que o `xmldsig-core-schema.xsd` genérico deixa `Algorithm` como `anyURI`
livre e que consultar o XSD não responderia nada. **Está errado, e a resposta é diferente em
cada versão.** O ZIP oficial traz os dois schemas:

| | `Schemas/1.00/xmldsig-core-schema.xsd` | `Schemas/1.01/xmldsig-core-schema.xsd` |
|---|---|---|
| Tamanho | 3.406 bytes (variante restrita do governo) | 10.610 bytes (W3C genérico) |
| `CanonicalizationMethod` | `fixed="...REC-xml-c14n-20010315"` | livre |
| `SignatureMethod` | `fixed="...xmldsig#rsa-sha1"` | livre |
| `DigestMethod` | `fixed="...xmldsig#sha1"` | livre |
| `Transform` | `minOccurs="2" maxOccurs="2"` | livre |
| `KeyInfo` | obrigatório | `minOccurs="0"` |

O governo **desfez** a restrição na v1.01. Isso explica a divergência entre as duas libs
concorrentes: cada uma mirou uma versão do schema.

Regra de implementação que sai daí: a forma de assinatura de v1.00 (exatamente dois
transforms, `KeyInfo` presente, C14N `REC-xml-c14n-20010315`) valida **sob os dois schemas**.
Só o par de hash é irreconciliável. Então construa sempre a forma estrita e varie só o hash.

### Defeito no XSD 1.01 publicado (achado em 2026-08-11, ao começar o v0.2.0)

`Schemas/1.01/tiposSimples_v1.01.xsd` define a série da DPS assim:

```xml
<xs:simpleType name="TSSerieDPS">
  <xs:restriction base="xs:string">
    <xs:pattern value="^0{0,4}\d{1,5}$"/>
```

Em XML Schema o `pattern` já é **ancorado implicitamente**, e `^` e `$` **não são
âncoras** — são caracteres literais. O padrão portanto exige que o valor comece com `^`
e termine com `$`. Verificado com `lxml`:

| valor de `serie` | resultado |
|---|---|
| `900` | REJEITA |
| `1` | REJEITA |
| `00001` | REJEITA |
| `^900$` | ACEITA |

A 1.00 não tem esse problema: lá `TSSerieDPS` é só `minLength 1 / maxLength 5`, sem
`pattern`. É o único padrão com âncora literal nos 10 arquivos da 1.01.

Três consequências:

1. **Nenhuma DPS valida localmente contra `Schemas/1.01/`.** Toda DPS tem `serie`. O
   critério de sucesso "a assinatura valida contra os dois schemas" continua alcançável
   porque `xmldsig-core-schema.xsd` é arquivo à parte; validar o **corpo** da DPS sob a
   1.01 não é.
2. **O XSD 1.01 publicado não pode ser o que a SEFIN usa.** O `pynfse-nacional` emite com
   `versao="1.01"` e afirma funcionar em produção. Se funciona, o servidor valida com
   outra coisa. Isso reforça o Approach C: a documentação não decide, o servidor decide.
3. Vale reportar ao gov.br, e avisar `nfelib`, `brans-nfe` e `pynfse-nacional` — qualquer
   um que tente validar 1.01 localmente vai bater nisso.

### Esquemas (rebaixa OQ1 de gate a item de roadmap)

Baixado `nfse-esquemas_xsd-v1-01-20260209.zip` de gov.br/nfse. Duas correções factuais:

1. **A data está errada no plano original.** O ZIP publicado é `v1-01-20260209`, não
   `v1-01-20260122`. Bate com a data do Anexo I deste repo.
2. **O ZIP traz `Schemas/1.00/` e `Schemas/1.01/` lado a lado**, e `tiposSimples_v1.01.xsd`
   documenta o tipo de versão como:

```xml
<xs:simpleType name="TVerNFSe">
  <xs:documentation>Tipo Versão da NF-e - 1.00|1.01</xs:documentation>
```

As duas versões são simultaneamente válidas. O `nfelib` 2.5.2 cobre a 1.00 por completo, e
`versao="1.00"` não é legado — é uma das duas opções correntes. Isso é o que rebaixa OQ1:
não existe um leiaute obsoleto a ser alcançado, existem dois vivos.

Delta medido da 1.01:

```
IBSCBS em Schemas/1.00/*.xsd .................. 0
IBSCBS em Schemas/1.01/tiposComplexos_v1.01.xsd  28
IBSCBS nos outros 9 arquivos de Schemas/1.01/ .. 0
targetNamespace 1.00 e 1.01 ................... http://www.sped.fazenda.gov.br/nfse (idêntico)
```

A camada da reforma tributária está contida em **um único arquivo** e o namespace não mudou.
Regenerar com `xsdata` é uma execução, não um projeto.

`nfelib` continua em 2.5.2 (30/03/2026), sem release novo. A regeneração para `v1_1` segue
sendo trabalho nosso.

### Acesso e certificado (fecha OQ6)

```
GET https://sefin.producaorestrita.nfse.gov.br/SefinNacional/   -> HTTP 403
GET https://adn.producaorestrita.nfse.gov.br/contribuintes/...  -> conexão derrubada
```

O handshake TLS do ADN emite `Request CERT` com 20 KB de lista de CAs (a cadeia ICP-Brasil) e
encerra a conexão quando o cliente apresenta lista vazia. O SEFIN completa o TLS e responde
403. **Nenhum endpoint responde sem certificado cliente, inclusive o Swagger.**

Consequência direta: a justificativa "o `doctor` é útil no primeiro minuto, antes de você ter
certificado de produção" está morta. O `doctor` continua sendo a primeira feature, mas pela
razão certa — ele encurta o tempo entre *ter* um certificado e *emitir a primeira nota* —
não porque dispensa o certificado.

Consequência secundária: o Swagger de produção restrita, que a revisão 2 apontava como fonte
para OQ2 e OQ3, é inacessível de mesa. Foi por isso que a resposta veio das implementações
concorrentes, e não da documentação.

### DANFSe (fecha OQ7)

`GET {ADN}/danfse/{chave}` existe e devolve o PDF oficial. As duas libs usam, e as duas
apontam para a **raiz do ADN**, não para o SEFIN e não para `/contribuintes`:

```python
# brans-nfe/client.py:239   (adn_url = "https://adn.nfse.gov.br", host nu)
url = f"{self.adn_url}/danfse/{chave_acesso}"
# pynfse-nacional/client.py:1269
danfse_base_url = self.base_url.replace("sefin.", "adn.").replace(...)
```

`brans-nfe` inclusive faz retry em 502/503/504 e levanta `DanfseIndisponivelError`, o que
sugere que o endpoint é instável — vale registrar como comportamento esperado.

A revisão 2 dizia que sem spec de leiaute o v0.4.0 seria "reimplementar o DANFSe em
`reportlab` do zero, um projeto do tamanho do resto da biblioteca". Não é preciso: baixa-se.
Geração local vira feature opcional, não obrigação.

### O achado que decide o design

As duas libs concorrentes fizeram escolhas **opostas em todos os eixos**:

| | `pynfse-nacional` 0.9.5 | `brans-nfe` 0.2.0 |
|---|---|---|
| Maturidade | 12 releases, site de docs, 9★ | 2 releases, 1★ |
| Licença | AGPL-3.0-only (verificado no `LICENSE` e no classifier) | MIT |
| `DPS versao=` | **1.01** | **1.00** |
| Assinatura | signxml, **rsa-sha256** / sha256 | lxml na mão, **rsa-sha1** / sha1 |
| `pedRegEvento versao=` | **1.00** | **1.01** |
| Base | XML na mão com ElementTree | `nfelib` + patch de enum |

Cruzadas em DPS e em evento. As duas afirmam funcionar em produção.

Só há três leituras possíveis: o servidor aceita ambos os pares; uma das duas está quebrada
e ninguém notou; ou a aceitação mudou no tempo. **Nenhuma delas é decidível sem um
certificado real contra produção restrita** — e essa é exatamente a lacuna que o `doctor`
existe para preencher.

Nota lateral com valor de implementação: `brans-nfe/_patches.py` corrige em runtime o enum
`TstipoRetPiscofins` do `nfelib`, que sai incompleto do gerador. É evidência concreta de que
bindings gerados têm buracos e de que `adapters/` precisa ser o dono declarado desses
remendos.

## Constraints

- **Licença MIT** obrigatória — é a razão de existir do projeto.
- **Python 3.10+**, `mypy --strict`, type hints completos em toda API pública.
- **Thread-safe**: `NFSeClient` instanciado uma vez, reutilizado em múltiplas threads.
  Sem estado mutável por requisição na instância.
- **Nunca logar chave privada.** Logger nomeado `nfse_sefin`, `logging` padrão, nunca `print`.
  `DEBUG` para payload XML, `INFO` para eventos de negócio.
- **Dependências mínimas** no núcleo: `nfelib`, `httpx`, `cryptography`, `lxml`.
  PDF via extra `[pdf]`. Ver a nota sobre `signxml` em Premissas (P10).
- API é **REST pura**. Não usar `zeep`, `suds` ou qualquer stack SOAP.
- Certificado ICP-Brasil A1 (`.pfx`), autenticação por **mTLS**, obrigatório em todos os
  endpoints. A3 (token/smartcard) é **não-objetivo declarado** do v1.
- **Sem prefixo de namespace no XML enviado.** `RN_RECEPCAO_DPS` #14 rejeita com **E1228**.
  Serializers do `xsdata` emitem `ns0:` com facilidade — falha de primeira requisição para
  quem chamar `to_xml()` ingenuamente. Precisa de teste dedicado.
- **UTF-8 obrigatório.** `RN_RECEPCAO_DPS` #15, **E1229**.
- Payload de `POST /nfse`: XML assinado → **gzip** → base64 → campo `dpsXmlGZipB64` de um
  envelope JSON. **Verificado.**

## Premises

P1, P2, P4, P5, P6, P7, P8 e P9 vêm da revisão 2 e seguem válidas. P3 foi reescrita.
P10 a P13 são novas.

**P1. O espaço não está vazio.** Dois clientes REST demonstráveis (`pynfse-nacional`,
`brans-nfe`), uma biblioteca de bindings (`nfelib`, que não é cliente), um pacote que ocupa
o nome sem cobertura verificável, e um pacote fiscal amplo (`erpbrasil.edoc`).

**P2 (refeita em 2026-08-11 — a premissa estava errada e o nome mudou).**

A revisão 3 concluiu que `nfsenacional` estava livre porque a API do PyPI devolvia 404.
**404 significa "não registrado", não "registrável".** Ao cadastrar o pending publisher,
o PyPI recusou: *"O nome do projeto é muito semelhante a um projeto existente"*.

A regra que pegou: o PyPI compara nomes **removendo todos os separadores**.
`nfse-nacional` (mupisystems) vira `nfsenacional` — o nome pedido era colisão exata desde
o início, e o método de verificação por 404 nunca teria detectado isso.

**Nome escolhido: `nfse-sefin`**, pacote de import `nfse_sefin`. Mantém "nfse", que é o
que o dev de ERP digita na busca, e troca a segunda palavra inteira, o que o afasta do
nome bloqueado sem depender de sorte na checagem de similaridade. Também é preciso: quem
emite é a SEFIN, distinção que esta revisão existe para registrar.

Verificação correta, para a próxima vez: além do 404, conferir que o nome **sem
separadores** não coincide com o de nenhum projeto existente do espaço.

**P3 (reescrita). `nfelib` é a base certa, e o teto que a revisão 2 enxergou não existe do
jeito que ela descreveu.**

A revisão 2 tratava `nfelib` como "atrasado" em relação ao leiaute do repo e transformava
isso num gate. O dado desfaz o enquadramento: `TVerNFSe` aceita `1.00|1.01`, o ZIP oficial
publica os dois schemas juntos, e o namespace é idêntico. `versao="1.00"` não é dívida — é
uma das duas opções correntes, e é a que `brans-nfe` usa em produção.

O que continua verdadeiro: a 1.01 traz IBS/CBS e o `nfelib` não a empacota. O que muda é o
custo e a urgência. O delta está em um arquivo, 28 ocorrências, mesmo namespace. `xsdata
generate` sobre `Schemas/1.01/` produz `v1_1`; PR para o `nfelib` e vendorização enquanto
não mergeia. O anexo já diz que para optantes do Simples Nacional os grupos IBS/CBS só
passam a ser obrigatórios em 2027.

**P4. `cert=(cert_pem_path, key_pem_path)` grava a chave privada ICP-Brasil em disco, em
claro.** `ssl.SSLContext.load_cert_chain` só aceita caminhos de arquivo. Padrão correto:
escrever com 0600 → fechar → `load_cert_chain` → `os.unlink` (o contexto retém o material).
A ordem importa: no Windows, `os.unlink` de arquivo ainda aberto falha. `memfd_create` +
`/proc/self/fd/N` evita o disco por completo, mas é só Linux — otimização, não caminho padrão.

**P5. O contrato público esboçado no plano original diverge do leiaute, em dois campos.**
`Servico(codigo_servico="01.01")` → o campo real é `cTribNac`, 6 dígitos numéricos.
`competencia="2026-07"` → `dCompet` é tipo `D`, **AAAA-MM-DD**, data completa.

**P6. "Obrigatória para todos os municípios desde janeiro de 2026" é meia-verdade.**
Município que não aderir perde transferências voluntárias federais (LC 214/2025), mas a
emissão não migrou toda: municípios com sistema próprio seguem com `ambGer=1`. A consulta
de convênio é o **passo zero**, não o passo 3.

**P7. Validar localmente só o que é decidível offline.** Dígito verificador de CPF/CNPJ,
formato de CEP, código IBGE de 7 dígitos, `dCompet` AAAA-MM-DD, existência do `cTribNac` na
lista de 337 subitens, e o que o próprio XSD já cobre. Fora da lista offline: a matriz de
compatibilidade de eventos, que exige `GET /nfse/{chave}/eventos` — decidível **após uma
consulta**, e é assim que `eventos/` deve documentar.

**P8. `POST /nfse` não entra em retry automático.** Escrita fiscal síncrona e não
idempotente; E0014 rejeita série+número+município+CNPJ repetidos. Retry só em GET e HEAD.
Em falha ambígua, o caminho documentado é `HEAD /dps/{id}` e depois `GET /dps/{id}`.

**P9. A biblioteca não é dona da sequência `nDPS`.** A fachada exige `serie` e `nDPS` do
chamador e documenta que unicidade e persistência do contador são responsabilidade do ERP
hospedeiro.

**P10 (nova). `signxml` é escolha condicional, não default.** Sob v1.00 o schema fixa
`rsa-sha1`, e o `signxml` atual recusa RSA-SHA1 por padrão nos dois sentidos, exigindo
opt-in explícito. `brans-nfe` resolveu abandonando o `signxml` e montando `SignedInfo` na
mão com `lxml` + `cryptography` — cerca de 60 linhas. `pynfse-nacional` usa `signxml`
porque escolheu SHA256. Como o Approach C precisa emitir os dois pares, a implementação
manual cobre ambos com um único caminho de código e sem brigar com o default de uma
dependência. Decisão: **assinar com `lxml` + `cryptography`, sem `signxml` no núcleo.**

**P11 (nova). O contrato de erro da SEFIN não é estável.** Quatro formatos observados em
produção. `errors.py` normaliza as quatro e nunca assume forma única. Evidência:
`pynfse-nacional/client.py:535-600`.

**P12 (nova). Eventos e DPS falam contratos diferentes.** Resposta de evento é
`{"retEvento": {"cStat": 144, "xMotivo", "idEvento"}}` no idioma SEFAZ; resposta de DPS é
`{"chaveAcesso", ...}` com `{"erro": [...]}`. Modelar como dois contratos, não um.

**P13 (nova). Existe um quarto grupo de endpoints que o design nunca contemplou.** O manual
`manual-contribuintes-apis-adn-sistema-nacional-nfse.pdf` (v1.0, 12/02/2026, publicado em
gov.br/nfse e ausente deste repo) descreve a API de Distribuição: `GET {ADN}/contribuintes/DFe/{NSU}`
devolve documentos fiscais em que o contribuinte figura como emitente, tomador ou
intermediário, com validação de CNPJ raiz contra o certificado da conexão. É como um ERP
**recebe** notas emitidas contra ele. Fora do escopo do v0.2.0, mas é escopo real da
biblioteca e merece lugar no roadmap em vez de ser redescoberto depois.

## Landscape

Verificado contra a API JSON do PyPI e os sdists baixados, em 2026-08-11.

| Pacote | Versão | Licença | Atividade | Cobertura |
|---|---|---|---|---|
| `pynfse-nacional` | 0.9.5 (2026-07-14) | **AGPL-3.0-only** (confirmado no `LICENSE` e no classifier) | 12 releases, docs site, 9★ | cliente completo: emissão, consulta, cancelamento, substituição, DANFSe (download e geração), convênio |
| `brans-nfe` | 0.2.0 (2026-06-10) | MIT | 2 releases, 1★ | cliente: mTLS A1, XMLDSIG manual, gzip+b64, cancelamento, DANFSe, DFe |
| `nfelib` | 2.5.2 (2026-03-30) | MIT | 23 releases, 204★ | **não é cliente** — bindings gerados por `xsdata`, esquema v1.00 apenas |
| `nfse-nacional` | 0.1.0 (2026-01-05) | MIT | 1 release, 7 meses parado | ocupa o nome no PyPI |
| `erpbrasil.edoc` | 3.1.1 | MIT | 27 releases | amplo demais, abstração errada |

**A brecha continua de pé, e agora está verificada na fonte:** o único concorrente maduro é
AGPL-3.0-only. Um ERP proprietário de petshop, clínica ou salão não pode linkar sem abrir o
código. É exatamente o público-alvo declarado. `brans-nfe` é MIT e tem a arquitetura certa,
mas 2 releases e 1 estrela.

## Approaches Considered

A decisão desta sessão foi qual par (versão de leiaute, algoritmo de assinatura) o v0.2.0
emite. Os três caminhos:

### Approach A: Par 1.00 + RSA-SHA1 (rota do `brans-nfe`)

`nfelib` 2.5.2 sem regeneração. Assinatura na forma que o XSD 1.00 fixa: C14N
`REC-xml-c14n-20010315`, `rsa-sha1`, `sha1`, exatamente dois transforms, `KeyInfo` presente.

- **Effort:** S (human ~1 semana / CC ~3h) · **Risk:** Med · **Completeness:** 6/10
- **Pros:** zero trabalho de binding; é a combinação de uma implementação MIT que existe e
  roda; a forma estrita valida sob os dois schemas.
- **Cons:** sem IBS/CBS, com teto conhecido em 2027; SHA1 numa biblioteca nova em 2026 é
  escolha difícil de defender; aposta cega em um dos dois pares sem poder testar.
- **Reuses:** `nfelib` v1_0, `lxml`, `cryptography`, `httpx`.

### Approach B: Par 1.01 + RSA-SHA256 (rota do `pynfse-nacional`)

`xsdata generate` sobre `Schemas/1.01/`, gerar `v1_1`, PR para o `nfelib`, vendorizar até o
merge. Assinatura SHA256, permitida pelo schema genérico da 1.01.

- **Effort:** M (human ~2 semanas / CC ~6h) · **Risk:** Med · **Completeness:** 8/10
- **Pros:** IBS/CBS coberto antes de 2027 virar prazo; hash moderno; é a combinação do
  concorrente mais maduro; delta está em um arquivo só e o namespace não muda.
- **Cons:** aceitação de `versao="1.01"` pelo servidor não está verificada; cria dívida de
  vendorização até o PR upstream mergear; aposta cega igual à de A, no outro par.
- **Reuses:** `xsdata`, XSDs oficiais, `lxml`, `cryptography`, `httpx`.

### Approach C: Par parametrizado + `doctor` descobre empiricamente ← ESCOLHIDA

Um eixo interno `(versao, hash, módulo de binding)` com dois valores válidos. `adapters/`
é o único lugar que conhece o eixo. O `doctor` emite uma DPS de teste em produção restrita
nos dois pares e reporta qual o servidor aceita, com o código `E####` da rejeição do outro.
O default da biblioteca segue o resultado.

- **Effort:** M (human ~3 semanas / CC ~1 dia) · **Risk:** Low · **Completeness:** 10/10
- **Pros:** converte o maior risco não verificável do projeto na feature de manchete;
  o usuário não precisa saber a resposta, que é literalmente a promessa do projeto; quando
  a SEFIN mudar de postura, a biblioteca descobre sozinha em vez de quebrar em campo;
  o custo incremental sobre B é pequeno porque os dois caminhos diferem em três parâmetros,
  não em arquitetura.
- **Cons:** o `doctor` passa a precisar de certificado real e de emitir nota de teste em
  produção restrita para dar resposta completa — deixa de ser puramente read-only.
- **Mitigação:** o `doctor` roda em modo degradado sem emissão (valida certificado,
  convênio, handshake) e só entra no probe dos dois pares com `--probe-assinatura` explícito.
- **Reuses:** tudo de A e de B.

### Alternativa descartada: contribuir para `brans-nfe`

MIT, já usa `nfelib`, arquitetura certa. O ecossistema Python fiscal brasileiro sofre de
fragmentação, não de escassez — uma quinta biblioteca tem custo social real. Descartada
porque tem 2 releases, 1 estrela e nenhum sinal de que o mantenedor quer co-manutenção.
**Mas o custo de perguntar é 10 minutos** e continua sendo a primeira tarefa da lista.

## Recommended Approach

**Approach C**, com a ordem de release da revisão 2 preservada (diagnóstico primeiro,
emissão depois).

A razão é o dado desta sessão. Duas bibliotecas em produção escolheram combinações opostas
de versão e de hash, e nenhuma documentação oficial acessível decide entre elas. Escolher A
ou B é apostar num dos dois sem evidência. C recusa a aposta e transforma a incerteza em
funcionalidade — que é a única resposta compatível com "mínimo de configuração possível":
se nem os autores das libs concorrentes sabem qual par funciona, o dev de petshop
definitivamente não deveria precisar saber.

### Arquitetura

```
nfse_sefin/
  __init__.py          NFSeClient, Certificate, Ambiente, exports principais
  ambientes.py         enum Ambiente + QUATRO bases (SEFIN, ADN raiz, ADN parametrização, ADN contribuintes)
  cert.py              from_pfx(); ssl.SSLContext (write 0600 -> close -> load -> unlink)
                       detecção de PKCS#12 legado vs OpenSSL 3.x com mensagem acionável
  transport.py         httpx.Client mTLS; envelope JSON; gzip+base64 nos dois sentidos;
                       retry SÓ em GET/HEAD (P8); normalização das 4 formas de erro (P11)
  signing.py           XMLDSIG enveloped sobre infDPS, lxml + cryptography, SEM signxml (P10)
                       forma estrita (2 transforms + KeyInfo), hash parametrizado
  perfis.py            o eixo do Approach C: PERFIL_100 = (versao "1.00", sha1, bindings v1_0)
                                             PERFIL_101 = (versao "1.01", sha256, bindings v1_1)
  errors.py            NFSeError (base), CertificadoError, MunicipioNaoAderente,
                       TransporteError, RejeicaoNFSe, EventoRejeitado (idioma cStat, P12)
  convenio.py          preflight municipal contra {ADN}/parametrizacao/{codMun}/convenio
  doctor.py            CLI de diagnóstico; entry point `nfse-doctor`; --probe-assinatura
  facade/
    prestador.py  tomador.py  servico.py  dps.py  nfse.py        dados puros, sem nfelib
  catalogos/
    servicos.py        337 subitens; buscar_servico(texto); zfill(6) com assertion de build
    rejeicoes.py       429 regras com E####; caminho XML Optional (forward-fill de coluna)
    eventos.py         16 tipos + matriz de compatibilidade
  adapters/nfelib.py   ÚNICO dono da conversão fachada <-> bindings e do eixo de perfil;
                       dono declarado dos patches de binding incompleto
```

`facade/` são dataclasses puras, sem importar `nfelib`. `adapters/nfelib.py` é o único
módulo que importa `nfelib` e o único que converte. Isso mantém a fachada testável sem a
dependência e concentra a quebra de mapeamento num arquivo quando o leiaute mudar.

### Especificação de `signing.py`

- Assinatura **enveloped**, inserida como último filho de `<DPS>`, irmã de `<infDPS>`.
- `Reference URI` = `"#" + infDPS/@Id`.
- Transforms: exatamente dois — `enveloped-signature` seguido de C14N
  `http://www.w3.org/TR/2001/REC-xml-c14n-20010315`. Dois é o que o XSD 1.00 exige e o que
  a 1.01 aceita.
- `KeyInfo` com `X509Certificate` **sempre presente**. Obrigatório na 1.00, opcional na 1.01
  — emitir sempre valida sob as duas.
- `SignatureMethod` e `DigestMethod` vêm do perfil ativo, nunca hardcoded.
- **Nada re-serializa a árvore depois de assinada.** O byte assinado é o byte comprimido,
  codificado e enviado.
- **Sem prefixo de namespace** na saída (E1228) e **UTF-8** (E1229) — testes dedicados.

### `tpAmb`: dono definido

`NFSeClient.emitir()` **sobrescreve** `infDPS.tpAmb` a partir do `Ambiente` do cliente,
sempre, com `logging.WARNING` se o chamador tinha passado outro valor. O leiaute rejeita
quando o ambiente informado diverge do ambiente de recepção, e deixar isso na mão do
usuário garante que todo mundo tome essa rejeição uma vez.

### API pública v0.2.0

```python
from nfse_sefin import NFSeClient, Certificate, Ambiente
from nfse_sefin.errors import MunicipioNaoAderente, RejeicaoNFSe

cert   = Certificate.from_pfx("empresa.pfx", password="senha")
client = NFSeClient(cert, ambiente=Ambiente.PRODUCAO_RESTRITA)   # perfil auto

conv = client.consultar_convenio("3304557")        # passo zero, não passo 3
if not conv.aderido:
    raise MunicipioNaoAderente(conv)

nfse = client.emitir(dps)                          # fachada, objeto nfelib ou bytes de XML
doc  = client.consultar(nfse.chave_acesso)
pdf  = client.baixar_danfse(nfse.chave_acesso)     # GET {ADN}/danfse/{chave}

if client.dps_foi_processada(dps_id):              # HEAD /dps/{id}   -- recuperação P8
    chave = client.chave_por_dps(dps_id)           # GET  /dps/{id}
```

### Ordem de release

| Release | Módulos | Escopo |
|---|---|---|
| **v0.1.0** | `ambientes`, `cert`, `transport`, `errors` base, `convenio`, `catalogos/servicos`, `doctor` | Diagnóstico. Não emite nota. |
| **v0.2.0** | `perfis`, `signing`, `errors.RejeicaoNFSe`, `catalogos/rejeicoes`, `facade/*`, `adapters/nfelib`, `emitir`, `consultar`, `/dps/{id}`, `danfse` | Emissão, consulta e DANFSe |
| **v0.3.0** | `catalogos/eventos`, `eventos/` | cancelar, substituir, manifestar |
| **v0.4.0** | distribuição `GET /DFe/{NSU}` (P13) | receber notas emitidas contra o contribuinte |

`danfse` subiu para v0.2.0: é um GET que devolve PDF, não justifica release próprio.
Geração local de DANFSe sai do roadmap e vira extra opcional se alguém pedir.

### Estimativa de esforço

| Escopo | Humano | CC |
|---|---|---|
| ~~Gate OQ1 + OQ2~~ | — | **resolvido nesta sessão** |
| v0.1.0 | 2-3 semanas | 1 dia |
| v0.2.0 (inclui os dois perfis e o probe do doctor) | 4-6 semanas | 2-3 dias |
| v0.3.0 (eventos) | 2-3 semanas | 1 dia |
| v0.4.0 (distribuição DFe) | 1-2 semanas | meio dia |

Os geradores de catálogo seguem sendo trabalho não trivial: 373 KB de markdown exportado de
Excel, cabeçalhos multi-linha, células mescladas, colunas que exigem forward-fill, células
condicionais `X/V` na matriz de eventos, e zeros à esquerda perdidos (OQ5).

## Open Questions

Restam cinco. Nenhuma é gate — todas as que bloqueavam código foram resolvidas.

**OQ5. Zeros à esquerda no catálogo de serviços.** O leiaute define `cTribNac` como 6 dígitos
e o sample oficial usa `010101`, mas a tabela `MUN.INCID_INFO.SERV.` do Anexo I teve os
zeros comidos pelo Excel (`10101`, `50101`, `60301`). Um parse ingênuo produz códigos de 5
dígitos para cerca de um terço da lista. Requisito: `zfill(6)` mais assertion de build de
que todas as N entradas têm comprimento 6. O mesmo anexo usa ainda uma terceira notação em
texto corrido ("subitens 07.02.01, 25.05") que precisa de normalizador próprio.

**OQ8/OQ9. Geração do catálogo de rejeições.** `RN DPS_NFS-e` tem 656 linhas mas só **429**
carregam código `E####` — usar 656 gera ~227 entradas vazias. Das 429, **228 têm a célula
`CAMINHO NO XML` vazia** (o anexo só repete o caminho na primeira linha de cada grupo), então
o gerador precisa de forward-fill. Pior: as 16 regras de `RN_RECEPCAO_DPS` estão numa tabela
**sem coluna de caminho XML nenhuma**. Portanto `RejeicaoNFSe.caminho_xml` é `Optional[str]`.

**OQ10. Política de pin do `nfelib`.** Recomendação mantida: pin exato até o v0.2.0, faixa
depois que houver suíte de contrato. Ganha peso agora que `perfis.py` referencia dois
conjuntos de bindings, um deles vendorizado.

**~~OQ11. PKCS#12 legado vs OpenSSL 3.x.~~ RESOLVIDO em 2026-08-11, e a premissa caiu.**

A revisão 3 afirmava que `cryptography.pkcs12.load_key_and_certificates` falha em `.pfx`
ICP-Brasil A1 por causa das cifras legadas. **Não reproduz.** Um `.pfx` gerado com
`-certpbe PBE-SHA1-RC2-40 -keypbe PBE-SHA1-3DES -macalg SHA1` carrega sem reclamar sob
`cryptography` 50.0.0, que empacota o próprio OpenSSL 4.0.1 com esses algoritmos
disponíveis. O wheel oficial não passa pelo legacy provider do OpenSSL do sistema.

O problema real é outro, e sobrevive: `cryptography` levanta `Invalid password or PKCS12
data` **tanto** para senha errada **quanto** para algoritmo recusado. Pela exceção não dá
para saber qual dos dois é. É essa ambiguidade que gera o ticket de suporte, não a falha
em si — e ela atinge quem roda build ligada a um OpenSSL 3.x de sistema sem legacy
provider, não a instalação padrão via `pip`.

`cert.py` desfaz a ambiguidade sem parser ASN.1: procura no DER cru os dois OIDs de PBE
clássico (`1.2.840.113549.1.12.1.3` e `.1.6`) e escolhe a mensagem. Arquivo legado →
"a senha pode estar certa, confira a build do OpenSSL". Arquivo PBES2 → "a causa provável
é senha incorreta". Nos dois casos a mensagem entrega o comando `openssl pkcs12` que
separa os cenários. `Certificate.usa_cifras_legadas` expõe o mesmo sinal para o `doctor`.

**OQ12. Infraestrutura de teste de integração — subiu de prioridade.** No Approach C isso
deixou de ser só cobertura de teste: o probe de perfil do `doctor` é a feature de manchete e
não pode ser validado sem um certificado ICP-Brasil A1 real e um município conveniado.
Nenhum dos dois está confirmado como disponível. **É a maior dependência aberta do projeto.**

**OQ13 (nova). O probe do `doctor` emite nota de teste — qual o efeito colateral?** Produção
restrita é ambiente de teste, mas uma DPS aceita consome um `nDPS` da série usada e pode
gerar NFS-e de teste que precise ser cancelada. Definir: série reservada para probe, política
de limpeza, e o que acontece se o probe roda contra `Ambiente.PRODUCAO` por engano (proposta:
recusar, sem exceção).

## Success Criteria

**v0.1.0**
- `pip install nfse-sefin` e `nfse-doctor --municipio 3304557 --pfx empresa.pfx` funciona
  em menos de 5 minutos, partindo de zero, sem ler documentação.
- `nfse-doctor` tem código de saída distinto para: município não aderido, certificado
  inválido ou vencido, falha de handshake mTLS, PKCS#12 ilegível, sucesso.
- `catalogos/servicos.py` tem 337 entradas, todas com `cTribNac` de exatamente 6 dígitos —
  assertion no build, não no teste.
- `tests/test_nfelib_contract.py` faz o round-trip da DPS de exemplo e falha quando o
  `nfelib` publica esquema novo.
- Teste que fixa as quatro URLs base e falha se alguém apontar emissão para o ADN
  ou DANFSe para o SEFIN.
- `mypy --strict` limpo, `ruff` limpo.

**v0.2.0**
- Um dev de ERP emite uma NFS-e em produção restrita escrevendo menos de 30 linhas de
  Python, sem abrir o Anexo I.
- `nfse-doctor --probe-assinatura` responde qual perfil o servidor aceita e cita o `E####`
  da rejeição do outro.
- Rejeição da SEFIN vira exceção tipada com código, texto literal do anexo e — quando o
  anexo fornece — caminho XML (`Optional[str]`, OQ9).
- `errors.py` tem teste para as quatro formas de payload de erro observadas (P11).
- Teste provando que o XML assinado sobrevive ao caminho completo (assinar → gzip → base64
  → decodificar → descomprimir → verificar assinatura) sem re-serialização, **nos dois perfis**.
- Teste provando que a saída não tem prefixo de namespace (E1228) e é UTF-8 (E1229).
- Teste provando que a assinatura emitida valida contra `Schemas/1.00/xmldsig-core-schema.xsd`
  e contra `Schemas/1.01/xmldsig-core-schema.xsd` quando o perfil é o estrito.

## Distribution Plan

- **Canal:** PyPI, nome `nfse-sefin`. Pacote de import `nfse_sefin`. Build com `hatch`.
- **Entry point:** `[project.scripts]` → `nfse-doctor = "nfse_sefin.doctor:main"`.
- **Repositório:** GitHub público, MIT, `LICENSE` na raiz.
- **CI/CD:** GitHub Actions. Em PR: `ruff` + `mypy --strict` + `pytest` na matriz
  Python 3.10-3.13. Em tag `v*`: build e publish via **Trusted Publishing** (OIDC, sem token
  guardado no repo).
- **Job semanal** que reinstala `nfelib` na última versão e roda a suíte. Ressalva honesta:
  detecta releases do `nfelib`, não publicações do governo. Adicionar um segundo job que faz
  `HEAD` no `nfse-esquemas_xsd-*.zip` de gov.br e falha quando o nome do arquivo muda de data
  — foi exatamente assim que o `20260122` do plano virou `20260209` sem ninguém notar.
- **Schemas vendorizados:** commitar `Schemas/1.00/` e `Schemas/1.01/` no repo para validação
  local em teste, com procedência e data no README.
- **Docs:** README com exemplo que funciona no copy-paste; mkdocs a partir do v0.2.0.

## Next Steps

Sem gates. O caminho está livre para código.

1. ~~**Abrir issue no `brans-nfe`** perguntando se o mantenedor quer co-manutenção.~~
   **FEITO em 2026-08-11** — [badbrans/brans-nfe#3](https://github.com/badbrans/brans-nfe/issues/3).
   Aguardando resposta. **Data de corte: 2026-08-25.** Sem resposta até lá, tratar como
   "prefiro seguir sozinho" e continuar com biblioteca própria, sem reabrir a pergunta.

   Contexto que pesa na leitura do silêncio: o repo teve o último push em 2026-06-10 e
   nunca recebeu issue nem PR de fora — esta é a primeira interação externa da vida dele.
   Silêncio é resultado provável e não deve travar mais nada.

   Se a resposta for boa, este design vira roadmap de um repo que já existe. O `brans-nfe`
   já acertou transporte e assinatura (`transmitir()` sem retry, forma estrita no
   `signer.py`), o que torna a conversa mais valiosa, não menos. A lacuna dele é catálogo
   e diagnóstico — exatamente o que os itens 7 e 9 desta lista constroem.
2. **Resolver OQ12** — conseguir um certificado ICP-Brasil A1 e confirmar um município
   conveniado. É a maior dependência aberta e a única coisa que impede validar a feature de
   manchete. Comece por aqui em paralelo com o código.
3. ~~Esqueleto: `pyproject.toml`, `LICENSE` MIT, `.gitignore`, GitHub Actions,
   `Schemas/` vendorizado, e `tests/test_nfelib_contract.py`.~~ **FEITO em 2026-08-11.**

   Três coisas que a execução acrescentou ao que estava planejado:

   - **O ZIP oficial não sai por `curl`.** O WAF do gov.br devolve 403 para cliente
     não-browser. A página de listagem responde 200 com User-Agent de browser, mas o
     ZIP em si 403a de qualquer jeito — foi baixado por browser headless. É por isso
     que `watch-upstream.yml` monitora o **nome do arquivo** na página, não o arquivo.
   - **A cópia de esquemas da `nfelib` está atrás do oficial.** `tiposComplexos_v1.00`
     tem 78.115 bytes na `nfelib` 2.5.2 e 80.390 no ZIP publicado; `CNC_v1.00.xsd` e
     `tiposCnc_v1.00.xsd` nem existem lá. Vendorizar o oficial não é redundância.
   - **A armadilha do E1228 foi confirmada em execução.** O `XmlSerializer` do
     `xsdata` emite `ns0:` em todo elemento por padrão. A correção é
     `render(obj, ns_map={None: NAMESPACE})`, e o teste guarda **qualquer** prefixo,
     não a string literal `ns0:`.

   Fora de escopo por dependência que ainda não existe: o console script
   `nfse-doctor` está comentado no `pyproject.toml` porque `doctor.py` só entra no
   item 8, e declarar entry point antes disso instala um comando que quebra no import.
4. ~~`ambientes.py` — as quatro bases, com o teste que impede regressão para o ADN.~~
   **FEITO em 2026-08-11.** `Ambiente` carrega também o `tp_amb` do leiaute. Os guardas
   foram verificados por mutação: reintroduzir emissão-no-ADN, DANFSe-no-SEFIN e
   restrita-vazando-para-produção deixa a suíte vermelha nos três casos.
5. ~~`cert.py` — `from_pfx()`, `cn`, `validade`, aviso de vencimento, `ssl.SSLContext` com
   write→close→load→unlink em 0600, e detecção de PKCS#12 legado (OQ11).~~
   **FEITO em 2026-08-11.** Junto veio o mínimo de `errors.py` que o `cert.py` precisa.

   Duas decisões que a execução firmou:

   - **Carregar nunca valida.** Certificado vencido abre normalmente, e `exigir_valido()`
     é opt-in. O `doctor` precisa abrir o arquivo para conseguir dizer "venceu há 12 dias";
     estourar na carga deixaria o usuário sem diagnóstico nenhum.
   - **`repr` não vaza chave.** `Certificate` é frozen dataclass com `repr=False` nos
     campos de chave, certificado e cadeia. O `repr` automático despejaria material de
     chave privada em qualquer log que chamasse `print()`.

   A premissa do OQ11 caiu na verificação — ver OQ11 acima.
6. ~~`transport.py` — envelope JSON, gzip+base64, retry só GET/HEAD, normalização das
   quatro formas de erro (P11).~~ **FEITO em 2026-08-11.**

   O retry é decidido pelo **método**, não pelo status: `GET`/`HEAD` repetem em 5xx e em
   erro de rede, `POST` nunca. 4xx não repete nem em leitura — é decisão do servidor
   sobre aquela requisição, e repetir só atrasa o diagnóstico.

   Achado da execução: `gzip.decompress(b"")` devolve `b""` **sem levantar**. Sem guarda
   explícita, campo vazio na resposta viraria "XML vazio" e o problema só apareceria
   muito depois, num parse que não explica nada. `de_gzip_b64` recusa vazio nos dois
   lados (entrada e saída da descompressão).
7. ~~`errors.py` base + `catalogos/servicos.py` (zfill(6) e assertion de build, OQ5).~~
   **FEITO em 2026-08-11.** A base de `errors.py` já tinha entrado com os itens 5 e 6.

   **O número 341 estava errado: são 337.** Veio do plano original e se propagou até os
   critérios de sucesso. Varredura exaustiva das linhas de tabela da seção
   `MUN.INCID_INFO.SERV.` devolve 337 linhas de dado e 6 de cabeçalho, sem nenhuma
   escapando do padrão. Corrigido nas três ocorrências.

   O OQ5 se confirmou na medida certa: **118 dos 337** códigos perderam o zero à
   esquerda no export do Excel — 35%, o "cerca de um terço" que a revisão 2 estimou. O
   XSD é a autoridade e fixa `[0-9]{6}` com 2 dígitos de item, 2 de subitem e 2 de
   desdobro nacional, o que também deu a decomposição `item`/`subitem`/`desdobro`.

   O catálogo é **gerado** por `tools/gerar_catalogo_servicos.py`, com os dados embutidos
   no módulo — o anexo não vai na wheel. `--conferir` roda no CI e prova que o arquivo
   versionado é o que sai do anexo versionado, para que correção feita à mão não suma na
   próxima geração.

   Deliberadamente fora: as colunas X/- de localidade de incidência (EP/LP/ET/EDEmit). O
   significado delas depende de notas de rodapé do anexo, e mapear errado seria pior que
   não ter. A coluna de grupo obrigatório entrou porque é inequívoca — `obra` (13
   serviços) ou `atvEvento` (19).
8. ~~`convenio.py` + `doctor.py`~~ **CÓDIGO FEITO em 2026-08-11.** Publicação no PyPI
   pendente — ver "Pendências do v0.1.0" abaixo.

   **A rota do convênio continua indecidida, e o código não aposta.** O manual do
   Emissor Público v1.2 documenta `/parametros_municipais/{codMun}/convenio`; o
   `pynfse-nacional`, única implementação em produção com convênio, usa
   `{ADN}/parametrizacao/{codMun}/convenio`. Nada responde sem certificado (OQ6), nem
   o Swagger. `consultar_convenio` tenta as duas e o `doctor` reporta qual respondeu —
   mesmo princípio do par de assinatura.

   **A forma do corpo da resposta segue desconhecida, de propósito.** O manual descreve
   o serviço sem publicar schema, e a implementação concorrente também não a conhece:
   infere adesão pelo status e guarda o corpo sem tipar. Aqui é igual. Tipar campo não
   verificado seria inventar leiaute.

   **O `doctor` roda com `tentativas=1`.** Descoberto por teste: o retry padrão de
   leitura trocava a `SSLError` original pela falha da última tentativa — justamente a
   informação que o comando existe para dar — e custava 4,5 s de espera.

   Verificado contra o servidor real, não só mock: apontado para
   `adn.producaorestrita.nfse.gov.br` com certificado auto-assinado, o ADN recusa no
   TLS e o `doctor` classifica como `MTLS_FALHOU`. Confirma o OQ6 na prática.
9. `perfis.py` + `signing.py` manual + `catalogos/rejeicoes.py` + `facade/` + `adapters/` +
   `emitir`/`consultar`/`/dps/{id}`/`danfse` + `--probe-assinatura` — v0.2.0.

## v0.1.0 — PUBLICADO em 2026-08-11

`pip install nfse-sefin` → https://pypi.org/project/nfse-sefin/

Publicado por Trusted Publishing (OIDC), sem token guardado no repositório.
Repositório público. Instalação verificada num ambiente limpo a partir do PyPI: o
console script roda, o catálogo carrega com 337 serviços, o `zfill` devolve `010101`
para `10101`, e o `py.typed` viaja na wheel.

Duas correções que a preparação do release exigiu, ambas achadas ao verificar em vez
de assumir:

- **A versão tinha duas declarações.** `pyproject.toml` e `__init__.py`. O
  `release.yml` compara a tag com `__version__`, mas o artefato sai com o número do
  `pyproject` — divergência passaria pela guarda e publicaria outra versão. Agora o
  hatch lê de `__init__.py` e o `pyproject` declara `dynamic`.
- **`buscar_servico` não achava "banho e tosa"** — o caso de manchete escrito neste
  documento como a razão de o catálogo existir. A busca era só substring e a lista
  nacional não tem a palavra "tosa". Passou a ter três degraus: frase inteira, todos
  os termos, algum termo ordenado por quantos casaram.

Nada disso dependeu do OQ12: o `doctor` diagnostica sem emitir nota. O certificado
real continua sendo pré-requisito só do `--probe-assinatura`, na v0.2.0.

## Histórico de revisão

**Revisão 3.1 (2026-08-11)** — correção pontual, sem mudança de decisão:

- **DANFSe estava no host errado.** A revisão 3 registrou `GET {SEFIN}/danfse/{chave}` e
  afirmou que "as duas libs usam". Verificado na fonte dos dois sdists: as duas apontam para
  a **raiz do ADN**. `brans-nfe/client.py:239` concatena sobre `adn_url` (host nu, sem
  `/contribuintes`); `pynfse-nacional/client.py:1269` reescreve `sefin.` → `adn.` antes de
  concatenar `/danfse/{chave}`. São quatro bases, não três.

**Revisão 3 (2026-08-11)** — sessão de resolução de gates. Mudanças materiais:

- **URL base corrigida** — SEFIN (emissão) e ADN (consulta e parametrização) são hosts
  distintos. O design anterior mandava `POST /nfse` para o ADN, o que não emite nada.
  Três bases, não duas.
- **OQ2 resolvido: gzip**, confirmado em três implementações independentes.
- **OQ3 resolvido** — envelope `{"dpsXmlGZipB64": ...}`, resposta `nfseXmlGZipB64`, evento
  `pedidoRegistroEventoXmlGZipB64` / `retEvento.cStat`, contrato de erro em quatro formas.
- **OQ4 resolvido** — o XSD 1.00 fixa `rsa-sha1`, `sha1`, dois transforms e `KeyInfo`
  obrigatório; o 1.01 volta ao W3C genérico. A afirmação da revisão 2 de que o XSD "pode não
  responder nada" estava errada.
- **OQ1 rebaixado de gate** — `TVerNFSe` aceita `1.00|1.01`, o ZIP publica os dois schemas,
  namespace idêntico, IBS/CBS contido em um arquivo. Não há leiaute obsoleto.
- **OQ6 resolvido: não** — SEFIN devolve 403 e o ADN derruba a conexão sem certificado
  cliente. O Swagger é inacessível de mesa.
- **OQ7 resolvido** — `GET {ADN}/danfse/{chave}` devolve o PDF oficial. DANFSe sobe para
  v0.2.0 e deixa de ser projeto.
- **Approach C novo e escolhido** — perfil parametrizado com probe empírico no `doctor`,
  motivado pela descoberta de que as duas libs concorrentes escolheram pares opostos.
- **P3 reescrita**, **P10 a P13 novas** (`signxml` fora do núcleo; contrato de erro instável;
  eventos falam `cStat`; existe a API de distribuição `GET /DFe/{NSU}`).
- **`perfis.py` acrescentado** à arquitetura; `signing.py` reescrito para hash parametrizado
  e forma estrita compatível com os dois schemas.
- **v0.4.0 trocado** — era DANFSe contingente, virou distribuição de DFe.
- **OQ13 nova** — efeito colateral do probe de assinatura.
- **OQ12 subiu de prioridade** — deixou de ser cobertura de teste e virou dependência da
  feature de manchete.
- **Data do ZIP corrigida** — `v1-01-20260209`, não `20260122`.
