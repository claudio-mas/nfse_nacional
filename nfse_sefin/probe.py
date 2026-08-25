"""O probe de assinatura: descobrir qual perfil a SEFIN aceita **sem emitir nota**.

`perfis.py` explica por que a pergunta existe — as duas bibliotecas que existem para
esta API escolheram pares opostos e as duas afirmam funcionar. Este módulo é a resposta
empírica, e o desenho dele resolve a OQ13 do `DESIGN.md`.

## Por que não é preciso emitir

A pergunta original supunha que descobrir o perfil exige uma DPS aceita — que a resposta
útil é o `200`. Não é. Duas coisas já sabidas, postas lado a lado:

1. A forma estrita de assinatura da 1.00 valida sob **os dois** schemas; só o par de hash
   é irreconciliável.
2. `Schemas/1.00/xmldsig-core-schema.xsd` traz `fixed="...rsa-sha1"` e `fixed="...sha1"`.
   Uma assinatura SHA-256 ali não é assinatura *inválida* — é **falha de esquema**, e
   falha de esquema é E1235, regra de `RN_RECEPCAO_DPS`. A recepção roda antes de existir
   nota.

Logo: **uma requisição, com o par SHA-256**. Recusa vinda da recepção significa servidor
na 1.00; qualquer coisa além dela significa que a assinatura passou.

## O que o probe responde, e o que ele não responde

`Perfil` amarra **duas** coisas: a versão do leiaute, que vai no atributo `versao` da DPS,
e o par de hash. O raciocínio acima decide o hash — é o eixo em que os dois schemas
divergem de forma irreconciliável. A versão vai junto na mesma requisição, mas não é o que
está sendo medido.

Quase sempre isso não importa, porque o servidor responde sobre a assinatura antes de
chegar à versão. Quando importa, importa muito: um servidor que recuse `versao="1.01"`
por prazo expirado (E0001) responde pela camada de negócio, o que pela regra acima
significaria "a assinatura passou, use 1.01" — recomendando exatamente a versão que ele
acabou de recusar. Por isso E0001 tem tratamento próprio e devolve INDETERMINADO com as
duas metades ditas em separado. Ver `CODIGOS_DE_VERSAO_RECUSADA`.

## O estrago deliberado

Falta fechar o ramo do "passou" sem gerar documento. A DPS do probe carrega para isso um
defeito de propósito: `prest/regTrib/opSimpNac = 1` (Não Optante) **com** `indTotTrib`
informado, que é E0713.

É a escolha certa porque essa é justamente uma das regras que o XSD **não consegue**
expressar (ver `facade.tributos`): o documento é schema-válido, passa pela recepção, e
morre na regra de negócio — sempre, sem depender da parametrização do município nem de
nenhum dado real do contribuinte.

O estrago não pode ser montado pela fachada: `DPS.__post_init__` aplica E0713 localmente,
que é o comportamento certo dela. Então o probe monta uma DPS **válida** (MEI, que tem
`indTotTrib` como padrão legítimo) e troca `opSimpNac` no XML já serializado, **antes** de
assinar. A assinatura cobre o documento estragado, que é exatamente o que se quer testar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from lxml import etree

from nfse_sefin.ambientes import Ambiente
from nfse_sefin.catalogos.rejeicoes import por_codigo
from nfse_sefin.cert import Certificate
from nfse_sefin.errors import DadosInvalidosError, ProbeEmProducaoError
from nfse_sefin.facade.dps import DPS
from nfse_sefin.facade.enums import OpcaoSimplesNacional
from nfse_sefin.facade.pessoa import Prestador
from nfse_sefin.facade.servico import Servico
from nfse_sefin.facade.tributos import TotalTributos
from nfse_sefin.perfis import PERFIL_100, PERFIL_101, Perfil

__all__ = [
    "Veredito",
    "ResultadoProbe",
    "SERIE_PROBE",
    "NUMERO_PROBE",
    "CODIGO_SERVICO_PROBE",
    "CODIGOS_QUE_RECUSAM_O_PERFIL",
    "CODIGOS_DE_DEFEITO_NOSSO",
    "CODIGOS_DE_VERSAO_RECUSADA",
    "FUSO_DO_PROBE",
    "PERFIL_DO_PROBE",
    "cnpj_do_certificado",
    "dps_do_probe",
    "com_estrago",
    "classificar",
    "recusar_producao",
]

SERIE_PROBE = "49999"
"""Série reservada, no topo da faixa de aplicativo próprio (1 a 49999).

Vale registrar o que ela **não** resolve: `nDPS` é sequencial do emitente, não alocado
pelo servidor, então DPS rejeitada não consome nada e o número segue reusável. Esta série
existe só para o ramo de contingência — se um probe for aceito apesar do estrago, o
documento nasce fora da numeração de produção do ERP, e não no meio dela.
"""

NUMERO_PROBE = "1"
"""Sempre o mesmo. O caminho normal nunca chega a consumir número."""

CODIGO_SERVICO_PROBE = "010101"
"""`cTribNac` de "Análise e desenvolvimento de sistemas".

Qualquer código da lista serviria: o documento morre antes de o serviço importar. Este é
fixo para que a DPS do probe seja reproduzível e para que o `--conferir` do catálogo
quebre se ele algum dia sumir da lista nacional.
"""

VALOR_PROBE = Decimal("1.00")

PERFIL_DO_PROBE = PERFIL_101
"""O par enviado. É o SHA-256 porque é ele que o XSD 1.00 recusa — e é a recusa que
carrega informação. Mandar SHA-1 primeiro passaria nos dois e não responderia nada."""

CODIGOS_QUE_RECUSAM_O_PERFIL = frozenset({"E1235", "E0714"})
"""Os códigos que significam "este par de assinatura não serve".

E1235 é a resposta esperada e a única de alta confiança: falha de esquema, que é como o
XSD 1.00 recusa `rsa-sha256`, e ela vem da recepção. E0714 ("Arquivo enviado com erro na
assinatura") entra porque um servidor pode conferir a assinatura na camada de negócio em
vez de na de esquema — e a nossa assinatura confere contra `verificar()` antes de sair,
então "erro na assinatura" sobrando é o algoritmo.

**E0717 e E0718 saíram daqui em 2026-08-25.** E0717 é "a assinatura é obrigatória" — o
servidor não achou `Signature` nenhuma, que é defeito nosso de envelope, da mesma classe
de E1228. E0718 é "a assinatura deve ser feita com o certificado do emitente" — o CNPJ
que assinou não bate com o que emite, que é `cnpj_do_certificado` tendo pegado os dígitos
errados, ou certificado de matriz para emitente filial. Nos dois casos o probe estaria
transformando um bug nosso numa recomendação confiante de perfil, que é exatamente a
troca que o resto deste módulo recusa fazer. Vão para `CODIGOS_DE_DEFEITO_NOSSO`.

O resto da recepção também não entra: E1225 (base64), E1228 (prefixo de namespace) ou
E1229 (UTF-8) significam que a nossa requisição está quebrada, não que o perfil foi
recusado.
"""

CODIGOS_DE_DEFEITO_NOSSO = frozenset({"E0715", "E0716", "E0717", "E0718"})
"""Recusas que falam do **nosso** certificado ou da nossa assinatura, não do perfil.

E0715 (certificado inválido), E0716 (fora do padrão), E0717 (assinatura ausente) e E0718
(assinante não é o emitente). Todas chegam pela camada de negócio, então sem esta lista
cairiam no ramo "passou pela recepção" e virariam uma recomendação de perfil apoiada num
certificado que o servidor acabou de recusar.
"""

CODIGOS_DE_VERSAO_RECUSADA = frozenset({"E0001"})
"""O servidor recusou a **versão do leiaute**, não a assinatura.

E0001 é "O prazo de aceitação da versão do leiaute da DPS expirou". Ele chega pela camada
de negócio, o que significa que a assinatura passou pela recepção — mas devolver
`PERFIL_101` aí seria recomendar `versao="1.01"` logo depois de o servidor dizer que não
aceita essa versão.

É o eixo que o probe **não** resolve numa requisição: `Perfil` amarra versão de leiaute e
par de hash, e uma resposta separa os dois. Quando isso acontece o probe diz o que sabe e
o que não sabe, em vez de escolher um dos dois perfis prontos.
"""

_FORMA_DE_REJEICAO = re.compile(r"^E\d{4}$")
"""A forma dos códigos do Anexo I.

Sem este filtro, um `"401"` de proxy ou um `"503"` de gateway — que `normalizar_mensagens`
entrega como `codigo` igual a qualquer outro — cairia no ramo "chegou à regra de negócio"
e viraria uma recomendação de perfil. `client.py` já mantém a mesma disciplina para
separar rejeição de falha HTTP.
"""

ORIGEM_RECEPCAO = "RN_RECEPCAO_DPS"

_CAMINHO_OP_SIMP_NAC = ".//{*}infDPS/{*}prest/{*}regTrib/{*}opSimpNac"

FUSO_DO_PROBE = timezone(timedelta(hours=-3))
"""Fuso fixo para a DPS do probe, em vez do relógio local.

`TSDateTimeUTC` só aceita deslocamento em horas inteiras, e `datetime.now().astimezone()`
num host em Asia/Kolkata (+05:30) ou Australia/Adelaide (+09:30) produz meia hora — o que
faria a fachada recusar a DPS e o probe morrer por causa do fuso da máquina, num
diagnóstico que não tem nada a ver com isso. O documento é descartado de qualquer jeito,
então nada aqui depende do relógio de parede local.
"""


class Veredito(Enum):
    """O que o probe conseguiu concluir."""

    PERFIL_ENCONTRADO = "perfil_encontrado"
    """O servidor respondeu de forma que identifica o perfil. `ResultadoProbe.perfil`."""

    INDETERMINADO = "indeterminado"
    """A resposta não responde a pergunta — requisição quebrada, ou código desconhecido."""

    NOTA_GERADA = "nota_gerada"
    """O estrago não segurou e o servidor aceitou. Defeito do probe, não resultado."""


@dataclass(frozen=True, slots=True)
class ResultadoProbe:
    """O que o probe descobriu, e por quê."""

    veredito: Veredito
    perfil: Perfil | None
    """O perfil a usar. `None` quando o veredito não é `PERFIL_ENCONTRADO`."""

    codigos: tuple[str, ...]
    """Os `E####` que o servidor devolveu, na ordem em que vieram."""

    motivo: str
    """Uma frase que explica a conclusão, para a saída do `doctor`."""

    chave_acesso: str = ""
    """Preenchida só em `NOTA_GERADA`: a nota que precisa ser cancelada à mão.

    Vem **como o servidor mandou**, sem normalizar. Aqui existe um documento fiscal e o
    que importa é o operador conseguir achá-lo; recusar a string por não ter 50 dígitos
    exatos trocaria "a nota é esta" por uma exceção, que é a pior troca possível neste
    ramo.
    """

    id_dps: str = ""
    """O identificador da DPS que o probe mandou.

    Também só em `NOTA_GERADA`, e é a rede de segurança da `chave_acesso`: quando o corpo
    da resposta não traz chave em nenhum dos nomes conhecidos, é por aqui que
    `chave_por_dps()` ainda acha a nota.
    """

    def __str__(self) -> str:
        return self.motivo


def recusar_producao(ambiente: Ambiente) -> None:
    """Levanta se o ambiente for produção. Sem flag de override, de propósito.

    O estrago deliberado é cinto e suspensório, não prova. Se o probe chegar em produção
    e for aceito por qualquer motivo que não previmos, o resultado é documento fiscal
    real — e cancelar é registro de evento, que esta versão não tem. O custo de recusar é
    o usuário trocar uma flag; o custo de aceitar é uma nota que não dá para desfazer.

    É **lista de permissão**, não de negação. `Ambiente` tem dois membros hoje e um
    `is Ambiente.PRODUCAO` daria no mesmo — mas o enum é API pública, e o dia em que
    alguém acrescentar um terceiro ambiente a negação passa a liberar em silêncio. Numa
    guarda cujo modo de falha é emitir documento fiscal, o padrão é falhar fechado.
    """
    if ambiente is not Ambiente.PRODUCAO_RESTRITA:
        raise ProbeEmProducaoError(
            f"O probe de assinatura envia uma DPS de verdade e só roda em "
            f"{Ambiente.PRODUCAO_RESTRITA.value}; recebi {ambiente.value}. "
            f"Use --ambiente {Ambiente.PRODUCAO_RESTRITA.value}."
        )


def cnpj_do_certificado(certificado: Certificate) -> str:
    """O CNPJ do titular, tirado do `CN`.

    Num e-CNPJ ICP-Brasil o Common Name vem como `RAZAO SOCIAL:CNPJ`. É de lá que sai,
    e não de um argumento de linha de comando, porque E0718 exige que quem assina seja o
    emitente: um CNPJ digitado à mão que não case com o certificado devolveria erro de
    assinatura e o probe leria isso como "perfil recusado".
    """
    _, separador, sufixo = certificado.cn.rpartition(":")
    digitos = "".join(c for c in sufixo if c.isdigit())
    if not separador or len(digitos) != 14:
        raise DadosInvalidosError(
            f"Não foi possível extrair o CNPJ do certificado. O CN é {certificado.cn!r}, "
            "e o probe espera o formato 'RAZAO SOCIAL:CNPJ' de um e-CNPJ ICP-Brasil. "
            "Certificado de pessoa física (e-CPF) não emite como prestador."
        )
    return digitos


def dps_do_probe(cnpj: str, municipio: str, ambiente: Ambiente) -> DPS:
    """Uma DPS **válida**, mínima, pronta para receber o estrago.

    Válida de propósito: é a fachada que garante que ela passa pela recepção, e é isso
    que faz a recusa que volta ser sobre a assinatura e não sobre outra coisa. O único
    defeito do documento é o que `com_estrago` acrescenta depois.
    """
    return DPS(
        prestador=Prestador(cnpj=cnpj, simples_nacional=OpcaoSimplesNacional.MEI),
        servico=Servico(
            codigo=CODIGO_SERVICO_PROBE,
            descricao="Probe de compatibilidade de assinatura — nfse-doctor.",
            valor=VALOR_PROBE,
            municipio_prestacao=municipio,
            total_tributos=TotalTributos.nao_informar(),
        ),
        serie=SERIE_PROBE,
        numero=NUMERO_PROBE,
        competencia=datetime.now(FUSO_DO_PROBE).date(),
        municipio_emissor=municipio,
        emitido_em=datetime.now(FUSO_DO_PROBE),
        ambiente=ambiente,
    )


def com_estrago(xml: bytes) -> bytes:
    """Troca `opSimpNac` para `1` (Não Optante), deixando `indTotTrib` no lugar.

    O par resultante é E0713 garantido, e é schema-válido — os dois valores existem no
    XSD, e o que os proíbe juntos é uma regra que só o anexo tem.

    Roda **antes** de assinar. Reserializar depois de assinar quebraria o digest.

    Raises:
        DadosInvalidosError: `opSimpNac` não foi encontrado. Sem o estrago o probe
            emitiria uma DPS válida, que é exatamente o que ele existe para não fazer —
            então isto falha alto em vez de seguir.
    """
    raiz = etree.fromstring(xml)
    elementos = raiz.findall(_CAMINHO_OP_SIMP_NAC)
    if len(elementos) != 1:
        raise DadosInvalidosError(
            f"A DPS do probe deveria ter exatamente um opSimpNac e tem {len(elementos)}. "
            "Sem o estrago deliberado o probe emitiria uma nota válida — abortado."
        )
    elementos[0].text = OpcaoSimplesNacional.NAO_OPTANTE.value
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def _e_da_recepcao(codigo: str) -> bool:
    return any(regra.origem == ORIGEM_RECEPCAO for regra in por_codigo(codigo))


def classificar(codigos: tuple[str, ...]) -> ResultadoProbe:
    """Lê a resposta do servidor por **camada**, não por código.

    É o que faz o probe funcionar sem município conveniado: se o município não aderiu, a
    recusa que volta é de negócio — e negócio já significa que a assinatura passou pela
    recepção, que é a única coisa que o probe pergunta.

    A ordem das quatro perguntas é deliberada, da mais específica para a mais geral:
    recusou a assinatura? é defeito nosso? recusou a versão? aí sim, passou.
    """
    # Só a forma `E####` do anexo conta como resposta. Um `"401"` de proxy ou um `"503"`
    # de gateway chegam pelo mesmo campo `codigo` e, sem este filtro, cairiam no ramo
    # "chegou à regra de negócio" — respondendo um perfil com base num erro de rede.
    conhecidos = tuple(c for c in codigos if _FORMA_DE_REJEICAO.match(c))

    recusaram = [c for c in conhecidos if c in CODIGOS_QUE_RECUSAM_O_PERFIL]
    if recusaram:
        return ResultadoProbe(
            veredito=Veredito.PERFIL_ENCONTRADO,
            perfil=PERFIL_100,
            codigos=codigos,
            motivo=(
                f"O servidor recusou {PERFIL_DO_PROBE.nome} com {', '.join(recusaram)}. "
                f"Use o perfil {PERFIL_100.nome}."
            ),
        )

    nossos = [c for c in conhecidos if c in CODIGOS_DE_DEFEITO_NOSSO]
    if nossos:
        return ResultadoProbe(
            veredito=Veredito.INDETERMINADO,
            perfil=None,
            codigos=codigos,
            motivo=(
                f"O servidor recusou o certificado ou a assinatura em si "
                f"({', '.join(nossos)}), o que fala do que **nós** mandamos e não do "
                "perfil. Confira se o certificado é ICP-Brasil, está válido, e se o CNPJ "
                "dele é o do emitente."
            ),
        )

    de_versao = [c for c in conhecidos if c in CODIGOS_DE_VERSAO_RECUSADA]
    if de_versao:
        return ResultadoProbe(
            veredito=Veredito.INDETERMINADO,
            perfil=None,
            codigos=codigos,
            motivo=(
                f"Meia resposta: a assinatura {PERFIL_DO_PROBE.hash_hashlib} passou pela "
                f"recepção, mas o servidor recusou a versão de leiaute "
                f"{PERFIL_DO_PROBE.versao} ({', '.join(de_versao)}). Nenhum dos dois "
                f"perfis prontos serve — {PERFIL_101.nome} tem a versão recusada e "
                f"{PERFIL_100.nome} tem o hash que este servidor não precisa. O que "
                f"parece servir é versão 1.00 com SHA-256, que não é perfil de fábrica. "
                "Reporte o caso."
            ),
        )

    da_recepcao = [c for c in conhecidos if _e_da_recepcao(c)]
    if da_recepcao:
        return ResultadoProbe(
            veredito=Veredito.INDETERMINADO,
            perfil=None,
            codigos=codigos,
            motivo=(
                f"A requisição foi recusada na recepção por {', '.join(da_recepcao)}, que "
                "não é uma resposta sobre a assinatura. Corrija isso e rode de novo."
            ),
        )

    if conhecidos:
        return ResultadoProbe(
            veredito=Veredito.PERFIL_ENCONTRADO,
            perfil=PERFIL_101,
            codigos=codigos,
            motivo=(
                f"A assinatura {PERFIL_DO_PROBE.nome} passou pela recepção — o servidor "
                f"chegou à regra de negócio e respondeu {', '.join(conhecidos)}. "
                f"Use o perfil {PERFIL_101.nome}."
            ),
        )

    if codigos:
        return ResultadoProbe(
            veredito=Veredito.INDETERMINADO,
            perfil=None,
            codigos=codigos,
            motivo=(
                f"O servidor respondeu {', '.join(codigos)}, que não tem a forma `E####` "
                "do anexo. Não é rejeição de leiaute, então não diz nada sobre o perfil."
            ),
        )

    return ResultadoProbe(
        veredito=Veredito.INDETERMINADO,
        perfil=None,
        codigos=(),
        motivo=(
            "O servidor recusou sem devolver código E####. Sem código não dá para saber "
            "em que camada a recusa aconteceu."
        ),
    )
