# Projeto: Biblioteca Python `nfse-nacional`

## Objetivo

Desenvolva uma biblioteca Python reutilizável, com **licença MIT**, para integração
com a API REST oficial do Sistema Nacional NFS-e (SEFIN Nacional / gov.br/nfse),
obrigatória para todos os municípios brasileiros desde janeiro de 2026.

A biblioteca deve poder ser instalada via `pip install nfse-nacional` e integrada
a qualquer sistema de gestão (petshop, clínica, salão, ERP etc.) com o mínimo
de configuração possível.

---

## Passo 0 — Leia os documentos de referência antes de escrever qualquer código

Os três documentos a seguir estão na pasta atual do projeto em formato Markdown
e contêm toda a especificação oficial. Leia-os integralmente antes de começar:

1. `manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e-v1-2-out2025.md`
   — descreve os 4 grupos de endpoints REST da API SEFIN.

2. `anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md`
   — 5 seções: lista nacional de serviços (341 subitens), cenários de exportação
   (112 cenários), regras de recepção/certificado (16 regras), leiaute completo da
   DPS/NFS-e (416 campos com caminho XML, tipo, ocorrência, tamanho e descrição) e
   regras de negócio (651 RNs aplicadas pela SEFIN na recepção).
   Nota: a linha com valor `#Ref` na coluna de numeração da seção `RN DPS_NFS-e`
   é uma inconsistência no documento original do governo (fórmula Excel quebrada),
   não uma falha de conversão — ignore e trate como sequência normal.

3. `anexo_ii-sefin_adn-pedregevt_evt-snnfse-v1-01-20260122.md`
   — 4 seções: 16 tipos de eventos de NFSe, matriz de compatibilidade entre eventos,
   leiaute do XML de evento e regras de negócio dos eventos.

Consulte também:
- **Swagger (produção restrita / homologação)**:
  https://adn.producaorestrita.nfse.gov.br/contribuintes/docs/index.html
- **Schemas XSD oficiais** (faça o download e salve em `schemas/`):
  https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
  — arquivo `nfse-esquemas_xsd-v1-01-20260122.zip`

---

## Arquitetura do projeto

```
nfse_nacional/
├── __init__.py                 # Exporta NFSeClient e models principais
├── exceptions.py               # NFSeError, DPSInvalidaError, APIError, CertificadoError
├── cert/
│   ├── __init__.py
│   └── certificate.py          # Certificate.from_pfx() — carrega .pfx com cryptography
├── models/
│   ├── __init__.py
│   ├── prestador.py            # @dataclass Prestador (CNPJ/CPF, IM, razão social, endereço)
│   ├── tomador.py              # @dataclass Tomador (CPF/CNPJ, nome, endereço)
│   ├── servico.py              # @dataclass Servico (código lista, discriminação, valores)
│   ├── dps.py                  # @dataclass DPS (agrega prestador, tomador, serviço + metadados)
│   └── nfse.py                 # @dataclass NFSeResponse (chave acesso, número, XML, PDF URL)
├── xml/
│   ├── __init__.py
│   ├── builder.py              # DPSBuilder: DPS → XML string (lxml)
│   ├── signer.py               # DPSSigner: assina XML com XMLDSIG (signxml)
│   └── validator.py            # DPSValidator: valida XML contra XSD (lxml etree)
├── api/
│   ├── __init__.py
│   ├── endpoints.py            # AMBIENTES dict com URLs base de cada ambiente
│   └── client.py               # SefinClient: HTTP mTLS via httpx, métodos por endpoint
├── eventos/
│   ├── __init__.py
│   └── manager.py              # EventoManager: cancelar(), substituir(), manifestar()
├── pdf/                        # Extras opcionais — instalar com pip install nfse-nacional[pdf]
│   ├── __init__.py
│   └── danfse.py               # DANFSeGenerator: gera PDF do DANFSe (reportlab)
schemas/                        # XSDs oficiais extraídos do ZIP do gov.br
tests/
│   ├── conftest.py
│   ├── test_cert.py
│   ├── test_models.py
│   ├── test_xml_builder.py
│   ├── test_xml_signer.py
│   └── test_api_client.py
pyproject.toml
README.md
.gitignore
```

---

## API pública esperada (contrato da biblioteca)

O código a seguir representa exatamente como um desenvolvedor usará a biblioteca.
Toda implementação deve convergir para esta interface:

```python
from decimal import Decimal
from nfse_nacional import NFSeClient
from nfse_nacional.cert import Certificate
from nfse_nacional.models import DPS, Prestador, Tomador, Servico

# 1. Carrega o certificado ICP-Brasil A1
cert = Certificate.from_pfx("certificado.pfx", password="senha_do_pfx")

# 2. Inicializa o cliente (ambiente: "producao_restrita" ou "producao")
client = NFSeClient(certificate=cert, ambiente="producao_restrita")

# 3. Verifica se o município aderiu ao SEFIN Nacional
convenio = client.consultar_convenio_municipal("3304557")  # Rio de Janeiro
print(convenio.aderido)        # True
print(convenio.regime_tributacao)

# 4. Constrói a DPS
dps = DPS(
    prestador=Prestador(
        cnpj="12345678000195",
        inscricao_municipal="123456",
        nome_razao_social="Petshop Exemplo Ltda",
        codigo_municipio_ibge="3304557",
        endereco_logradouro="Rua das Flores",
        endereco_numero="100",
        endereco_bairro="Centro",
        endereco_cep="20040020",
    ),
    tomador=Tomador(
        cpf="12345678901",
        nome="João da Silva",
    ),
    servico=Servico(
        codigo_servico="01.01",           # subitem da lista nacional de serviços
        discriminacao="Banho e tosa - Golden Retriever",
        valor_servico=Decimal("150.00"),
        codigo_municipio_incidencia="3304557",
    ),
    competencia="2026-07",                # YYYY-MM
    numero_dps=1,
    serie="PETS",
)

# 5. Emite a NFSe (gera XML, assina, envia POST /nfse)
nfse = client.emitir(dps)
print(nfse.chave_acesso)   # chave de 50 dígitos
print(nfse.numero)         # número sequencial da nota
print(nfse.xml)            # XML completo retornado pela SEFIN

# 6. Consulta NFSe já emitida
nfse = client.consultar(chave_acesso="...")

# 7. Cancela
client.cancelar(chave_acesso=nfse.chave_acesso, motivo="Serviço cancelado pelo cliente")

# 8. Substitui (cancela a anterior e emite nova)
nfse_nova = client.substituir(chave_acesso_original=nfse.chave_acesso, nova_dps=dps)
```

---

## Stack técnica

| Finalidade | Biblioteca | Observação |
|---|---|---|
| HTTP + mTLS | `httpx[http2]` | suporta client certificates nativamente |
| XML (geração e XSD) | `lxml` | ElementMaker para builder fluente |
| Assinatura XMLDSIG | `signxml` | método `XMLSigner` |
| Certificados (.pfx) | `cryptography` | `pkcs12.load_key_and_certificates()` |
| PDF DANFSe (opcional) | `reportlab` | extras: `pip install nfse-nacional[pdf]` |
| Testes | `pytest` + `pytest-httpx` | mock de requisições HTTP |
| Linting/formatação | `ruff` | |
| Build/packaging | `hatch` com `pyproject.toml` | |

**Não use** `suds`, `zeep` ou qualquer biblioteca SOAP — a API da SEFIN é REST pura.

---

## Informações técnicas da API SEFIN Nacional

### Ambientes

```python
AMBIENTES = {
    "producao_restrita": "https://adn.producaorestrita.nfse.gov.br/contribuintes",
    "producao":          "https://adn.nfse.gov.br/contribuintes",
}
```

### Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| `POST` | `/nfse` | Emissão síncrona — envia DPS assinada, retorna XML da NFSe ou erro |
| `GET` | `/nfse/{chaveAcesso}` | Consulta NFSe pela chave de acesso |
| `GET` | `/dps/{id}` | Recupera chave de acesso a partir do ID da DPS |
| `HEAD` | `/dps/{id}` | Verifica se NFSe foi gerada (sem retornar a chave) |
| `POST` | `/nfse/{chaveAcesso}/eventos` | Registra evento (cancelamento, substituição etc.) |
| `GET` | `/nfse/{chaveAcesso}/eventos` | Lista eventos de uma NFSe |
| `GET` | `/nfse/{chaveAcesso}/eventos/{tipo}` | Filtra eventos por tipo |
| `GET` | `/parametros_municipais/{codMun}/convenio` | Parâmetros do convênio municipal |
| `GET` | `/parametros_municipais/{codMun}/{codServico}` | Alíquotas por subitem de serviço |

### Autenticação

mTLS (Mutual TLS) com certificado ICP-Brasil A1 (arquivo `.pfx`).
O certificado é apresentado em cada requisição HTTP como client certificate.

```python
# Configuração do httpx com mTLS
import httpx
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, NoEncryption
)

client = httpx.Client(
    cert=(cert_pem_path, key_pem_path),   # ou usar ssl.SSLContext
    verify=True,
)
```

### Identificador da DPS

A chave que identifica unicamente uma DPS é composta por:
`{código IBGE 7 dígitos}{tipo inscrição 1 dígito}{CPF/CNPJ 14 dígitos}{série 5 dígitos}{número 15 dígitos}`

---

## Tarefa: implementar o projeto em fases

Execute as fases **em ordem**. Ao concluir cada fase, rode os testes antes de avançar.

### Fase 1 — Estrutura e configuração do projeto
- Crie o `pyproject.toml` com metadados, dependências e extras `[pdf]`
- Crie a estrutura completa de diretórios conforme a arquitetura acima
- Configure `ruff` no `pyproject.toml` (target Python 3.10, regras: E, F, I, UP)
- Crie `.gitignore` adequado para Python
- Crie `README.md` com instalação, exemplo de uso e link para a documentação oficial
- Crie `tests/conftest.py` com fixtures básicas (certificado mock, DPS de exemplo)

### Fase 2 — Módulo `cert`
- Implemente `Certificate.from_pfx(path, password)` usando `cryptography.hazmat.primitives.serialization.pkcs12`
- Exponha `certificate.cert_pem`, `certificate.key_pem` e `certificate.cn` (Common Name)
- Adicione `certificate.validade` e aviso se expirar em menos de 30 dias
- Escreva `tests/test_cert.py` com um `.pfx` de teste (gere um auto-assinado via `cryptography`)

### Fase 3 — Módulo `models`
- Implemente todos os dataclasses (`Prestador`, `Tomador`, `Servico`, `DPS`, `NFSeResponse`)
- Campos tipados com `Optional` onde o Anexo I indicar ocorrência `0-1` ou `0-N`
- Validações no `__post_init__`:
  - CNPJ: 14 dígitos, dígitos verificadores válidos
  - CPF: 11 dígitos, dígitos verificadores válidos
  - Código município IBGE: 7 dígitos numéricos
  - CEP: 8 dígitos numéricos
  - Competência: formato `YYYY-MM`
  - Valor serviço: `Decimal`, positivo
- Escreva `tests/test_models.py` cobrindo validações válidas e inválidas

### Fase 4 — Módulo `xml/builder`
- Leia o Anexo I (seção `LEIAUTE DPS_NFS-e`) para mapear cada campo ao seu XPath no XML
- Implemente `DPSBuilder.build(dps: DPS) -> str` usando `lxml.etree`
- Respeite o namespace definido nos XSDs oficiais (confirme no arquivo `.xsd`)
- Produza o XML canônico (C14N) necessário para assinatura
- Escreva `tests/test_xml_builder.py`:
  - Teste que o XML gerado é um XML válido
  - Teste que o XML contém os campos obrigatórios
  - Teste de validação contra o XSD (usando `lxml.etree.XMLSchema`)

### Fase 5 — Módulo `xml/signer`
- Implemente `DPSSigner.sign(xml_str: str, certificate: Certificate) -> str`
- Use `signxml.XMLSigner` com método `enveloped`
- O elemento assinado deve ser `InfDPS` com `Id` como referência
- Escreva `tests/test_xml_signer.py`:
  - Teste que o XML assinado contém o elemento `Signature`
  - Teste de verificação da assinatura com `signxml.XMLVerifier`

### Fase 6 — Módulo `api/client`
- Implemente `SefinClient` com `httpx.Client` configurado para mTLS
- Cada método do cliente corresponde a um endpoint (veja tabela acima)
- Trate erros HTTP: 400 (rejeição de negócio com código e mensagem), 401, 403, 500
- Lance `APIError` com `codigo`, `mensagem` e `http_status` do erro
- Implemente retry automático para erros 5xx (máx. 3 tentativas, backoff exponencial)
- Escreva `tests/test_api_client.py` usando `pytest-httpx` para mockar as requisições:
  - Teste de emissão com resposta de sucesso
  - Teste de emissão com rejeição (400 com código de erro)
  - Teste de consulta
  - Teste de cancelamento

### Fase 7 — Módulo `eventos`
- Implemente `EventoManager` com métodos `cancelar()`, `substituir()`, `manifestar()`
- O XML do evento segue o leiaute do Anexo II (seção `LEIAUTE EVENTO_PED.REG.EVENTO`)
- O evento também precisa de assinatura XMLDSIG
- Consulte a matriz de compatibilidade (seção `RN EVENTOSxEVENTOS`) para validar
  se o evento é permitido dado o estado atual da nota

### Fase 8 — `NFSeClient` (fachada pública)
- Implemente a classe `NFSeClient` que agrega os módulos anteriores
- Exponha os métodos `emitir()`, `consultar()`, `cancelar()`, `substituir()`,
  `consultar_convenio_municipal()` conforme o contrato de API definido acima
- `emitir()` deve: construir XML → assinar (XMLDSIG) → comprimir (GZip) →
  codificar (Base64) → POST /nfse → retornar `NFSeResponse`
  **ATENÇÃO**: o payload enviado ao POST /nfse deve ser o XML assinado, comprimido
  com GZip e codificado em Base64. Isso está especificado nas regras E1225 e E1226
  da seção `RN_RECEPCAO_DPS` do Anexo I e é obrigatório para qualquer envio.
- Escreva um teste de integração `tests/test_integration.py` (marcado com
  `@pytest.mark.integration`) que usa o ambiente de produção restrita com um
  certificado real (skippado por padrão, ativado via variável de ambiente)

---

## Restrições e boas práticas

- **Licença MIT**: inclua `LICENSE` na raiz e cabeçalho de licença nos arquivos `.py`
- **Python 3.10+**: use `match/case`, `X | Y` union types, `from __future__ import annotations`
- **Sem dependências desnecessárias**: o núcleo da biblioteca deve ter apenas
  `httpx`, `lxml`, `signxml` e `cryptography` como dependências obrigatórias
- **Thread-safe**: `NFSeClient` deve poder ser instanciado uma vez e reutilizado
  em múltiplas threads (não armazene estado mutável por requisição na instância)
- **Logging**: use o módulo padrão `logging` com logger nomeado `nfse_nacional`
  (nunca `print`); nível `DEBUG` para payloads XML, `INFO` para eventos de negócio
- **Secrets**: nunca logue o conteúdo da chave privada do certificado
- **Tipos**: use `mypy --strict` como padrão; todos os métodos públicos devem
  ter type hints completos
