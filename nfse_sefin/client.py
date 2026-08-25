"""`NFSeClient` — emitir, consultar, recuperar e baixar o DANFSe.

É o objeto que quem integra usa. Tudo abaixo dele já existe: a fachada monta, o
adapter serializa, `signing` assina, `transport` fala mTLS. Este módulo é a costura,
e as decisões que ele carrega são as quatro abaixo.

## O `tpAmb` é do cliente, não do chamador

`emitir` **sobrescreve** `infDPS/tpAmb` a partir do `Ambiente` configurado, sempre,
com `logging.WARNING` quando o valor era outro. O leiaute rejeita quando o ambiente
declarado diverge do ambiente que recebeu a requisição, e deixar isso na mão de quem
integra garante que todo mundo tome essa rejeição uma vez. Uma DPS montada para
produção restrita e enviada para produção seria emissão real com `tpAmb=2`.

## Rejeição não é erro de transporte

O `Transporte` levanta `TransporteError` para qualquer HTTP >= 400, porque nesse
nível não há como distinguir "o servidor caiu" de "o servidor recusou o conteúdo".
Aqui há: se a resposta traz códigos `E####`, é decisão de negócio, e vira
`RejeicaoNFSe` — que traduz o código para o texto do anexo e para o caminho XML do
campo culpado.

A diferença importa para quem chama: transporte às vezes passa na próxima tentativa;
rejeição devolve o mesmo erro para o mesmo XML, sempre.

## Falha ambígua de emissão tem caminho, e ele não é repetir

`POST /nfse` não é idempotente (P8). Quando a conexão cai sem resposta, a nota pode
ter sido gerada. Repetir produz `E0014` — série+número+município+CNPJ repetidos — e
apaga a informação de que a primeira funcionou.

O caminho documentado é consultar: `dps_foi_processada(id)` e depois
`chave_por_dps(id)`. `emitir` **não** faz isso sozinho, porque decidir entre
reconsultar, alertar um humano ou seguir com outro número é política do ERP. O que
ele faz é levantar uma exceção que carrega o `id` da DPS e diz qual é o caminho.

## Cada operação sabe em qual das quatro bases mora

`POST /nfse` e as consultas vão para a SEFIN. O DANFSe mora na **raiz do ADN**, e o
convênio na parametrização. Trocar as bases falha de um jeito ruim: `POST /nfse` no
ADN não emite nota nenhuma.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from nfse_sefin.adapters.nfelib import serializar
from nfse_sefin.ambientes import Ambiente, Bases, bases_de
from nfse_sefin.cert import Certificate
from nfse_sefin.convenio import Convenio, consultar_convenio
from nfse_sefin.errors import (
    DadosInvalidosError,
    MensagemSefin,
    RejeicaoNFSe,
    RespostaInvalidaError,
    TransporteError,
)
from nfse_sefin.facade.dps import DPS
from nfse_sefin.perfis import PERFIL_PADRAO, Perfil
from nfse_sefin.probe import (
    PERFIL_DO_PROBE,
    SERIE_PROBE,
    ResultadoProbe,
    Veredito,
    classificar,
    cnpj_do_certificado,
    com_estrago,
    dps_do_probe,
    recusar_producao,
)
from nfse_sefin.signing import assinar
from nfse_sefin.transport import (
    Transporte,
    de_gzip_b64,
    gzip_b64,
    normalizar_mensagens,
    primeiro_campo,
)

__all__ = ["NFSeClient", "NotaFiscal", "normalizar_chave", "CAMPO_DPS", "CAMPO_NFSE"]

logger = logging.getLogger("nfse_sefin")

CAMPO_DPS = "dpsXmlGZipB64"
"""Campo do envelope de `POST /nfse`. Verificado em três implementações."""

CAMPO_NFSE = "nfseXmlGZipB64"
"""Campo da resposta 2xx que traz a NFS-e gerada, também em gzip+base64."""

_CODIGO_DE_REJEICAO = re.compile(r"^E\d{4}$")
"""A forma dos códigos do Anexo I. É o que separa recusa de negócio de falha HTTP."""


def normalizar_chave(chave: str) -> str:
    """Aceita a chave de acesso nas duas formas em que ela circula.

    `TSChaveNFSe` é `[0-9]{50}`, mas o identificador da NFS-e tem 53 posições porque
    leva o literal `NFS` na frente — e é assim que ele aparece no XML da nota, no
    atributo `Id`. Quem copia de lá cola 53 caracteres; quem copia de um relatório
    cola 50. As duas resolvem para a mesma chave.

    O dígito verificador **não** é conferido: o algoritmo não está publicado em
    nenhum dos documentos de referência, e recusar uma chave válida por ter chutado
    o cálculo errado seria pior que não conferir.
    """
    limpo = "".join(c for c in chave.strip().upper() if c.isalnum())
    if limpo.startswith("NFS"):
        limpo = limpo[3:]
    if len(limpo) != 50 or not limpo.isdigit():
        raise DadosInvalidosError(
            f"Chave de acesso da NFS-e tem 50 dígitos (ou 53 com o literal 'NFS'); "
            f"recebi {len(limpo)} em {chave!r}."
        )
    return limpo


@dataclass(frozen=True, slots=True)
class NotaFiscal:
    """Uma NFS-e gerada ou consultada.

    `xml` é o documento oficial já descomprimido — é ele que se arquiva. Os demais
    campos são o que o envelope JSON trouxe junto, e vêm vazios quando o endpoint
    não os informa.
    """

    chave_acesso: str
    xml: bytes

    id_dps: str = ""
    """O identificador de 45 posições da DPS que originou a nota."""

    tipo_ambiente: str = ""
    versao_aplicativo: str = ""
    processada_em: str = ""

    alertas: tuple[MensagemSefin, ...] = ()
    """Avisos que acompanham uma emissão bem-sucedida. Não são rejeição."""

    dados: dict[str, Any] = field(default_factory=dict)
    """O corpo cru. Existe porque o contrato não é estável (P11) e um campo novo do
    servidor não deve exigir release desta biblioteca para ser acessível."""

    def __str__(self) -> str:
        return f"NFS-e {self.chave_acesso}"


class NFSeClient:
    """Cliente do Sistema Nacional NFS-e.

    Uma instância serve várias threads: não há estado mutável por requisição.

    ```python
    cert = Certificate.from_pfx("empresa.pfx", password="senha")
    with NFSeClient(cert, ambiente=Ambiente.PRODUCAO_RESTRITA) as cliente:
        if not cliente.consultar_convenio("3304557").aderido:
            ...
        nota = cliente.emitir(dps)
        pdf = cliente.baixar_danfse(nota.chave_acesso)
    ```
    """

    def __init__(
        self,
        certificate: Certificate,
        *,
        ambiente: Ambiente = Ambiente.PRODUCAO_RESTRITA,
        perfil: Perfil = PERFIL_PADRAO,
        transporte: Transporte | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """
        Args:
            certificate: certificado A1 já carregado.
            ambiente: decide as quatro bases **e** o `tpAmb` de toda DPS emitida.
                O padrão é produção restrita: emitir nota de verdade tem de ser
                escolha explícita de quem integra.
            perfil: o par (versão de leiaute, algoritmo de assinatura). Ver
                `perfis.py` — a combinação certa não é conhecida, é um parâmetro.
            transporte: injeta um `Transporte` pronto. Para teste, ou para
                compartilhar pool de conexões entre clientes.
            client: injeta o `httpx.Client`. Só para teste.
        """
        self.ambiente = ambiente
        self.perfil = perfil
        self.bases: Bases = bases_de(ambiente)
        self._proprio = transporte is None
        self._certificado = certificate
        self._transporte = transporte or Transporte(certificate, client=client)

    # ------------------------------------------------------------- emissão

    def emitir(self, dps: DPS) -> NotaFiscal:
        """Assina a DPS e envia. Devolve a NFS-e gerada.

        O `tpAmb` da DPS é sobrescrito pelo ambiente do cliente — ver a nota no topo
        do módulo.

        Raises:
            RejeicaoNFSe: o servidor recusou o conteúdo. `regras` traz o texto
                oficial de cada código e o caminho XML do campo culpado.
            TransporteError: a requisição não chegou a uma resposta utilizável. Se a
                falha foi ambígua — conexão perdida sem status —, a mensagem carrega
                o identificador da DPS e o caminho de recuperação.
            RespostaInvalidaError: o servidor respondeu 2xx sem chave de acesso.
        """
        dps = self._com_ambiente_do_cliente(dps)
        identificador = dps.identificador

        xml = assinar(serializar(dps, self.perfil), self._certificado, self.perfil)
        envelope = {CAMPO_DPS: gzip_b64(xml)}

        try:
            corpo = self._transporte.post_json(f"{self.bases.sefin}/nfse", envelope)
        except TransporteError as exc:
            raise self._traduzir_falha_de_emissao(exc, identificador) from exc

        return self._nota_de(corpo, exigir_xml=True)

    def _com_ambiente_do_cliente(self, dps: DPS) -> DPS:
        if dps.ambiente is self.ambiente:
            return dps
        logger.warning(
            "DPS %s foi montada para %s e está sendo enviada para %s; tpAmb sobrescrito para %s.",
            dps.identificador,
            dps.ambiente.value,
            self.ambiente.value,
            self.ambiente.tp_amb,
        )
        return dataclasses.replace(dps, ambiente=self.ambiente)

    @staticmethod
    def _traduzir_falha_de_emissao(exc: TransporteError, identificador: str) -> Exception:
        """Separa recusa de negócio de falha de transporte, e trata a ambígua."""
        if any(_CODIGO_DE_REJEICAO.match(m.codigo) for m in exc.mensagens):
            return RejeicaoNFSe(exc.mensagens, status_code=exc.status_code)

        if exc.status_code is None:
            # Sem status não houve resposta, e sem resposta não se sabe se o servidor
            # processou. Repetir seria tentar emitir a mesma nota duas vezes.
            return TransporteError(
                f"{exc} — a emissão pode ter sido processada. NÃO reenvie: consulte "
                f"dps_foi_processada({identificador!r}) e, se True, "
                f"chave_por_dps({identificador!r}).",
                status_code=None,
                mensagens=exc.mensagens,
                corpo=exc.corpo,
                metodo=exc.metodo,
                url=exc.url,
            )
        return exc

    # --------------------------------------------------------------- probe

    def probe_assinatura(self, codigo_municipio: str) -> ResultadoProbe:
        """Descobre qual perfil de assinatura este servidor aceita, **sem emitir nota**.

        Manda uma requisição só, com o par SHA-256, numa DPS estragada de propósito para
        que o ramo "a assinatura passou" também termine em rejeição. O desenho inteiro e
        o porquê de cada peça estão em `probe.py`.

        O `perfil` configurado neste cliente é ignorado: o probe usa o seu, senão não
        pergunta nada.

        Args:
            codigo_municipio: IBGE de 7 dígitos. Não precisa ser conveniado — município
                não aderente devolve código de negócio, que já responde a pergunta.

        Raises:
            ProbeEmProducaoError: o cliente está apontado para produção.
            DadosInvalidosError: o certificado não é um e-CNPJ, ou o estrago não pôde
                ser aplicado — nos dois casos o probe para antes de mandar qualquer coisa.
            TransporteError: a requisição não chegou a uma resposta.
        """
        recusar_producao(self.ambiente)

        dps = dps_do_probe(cnpj_do_certificado(self._certificado), codigo_municipio, self.ambiente)
        xml = assinar(
            com_estrago(serializar(dps, PERFIL_DO_PROBE)), self._certificado, PERFIL_DO_PROBE
        )

        try:
            corpo = self._transporte.post_json(
                f"{self.bases.sefin}/nfse", {CAMPO_DPS: gzip_b64(xml)}
            )
        except TransporteError as exc:
            return classificar(tuple(m.codigo for m in exc.mensagens if m.codigo))

        # Chegar aqui significa que o estrago não segurou. É defeito do probe, não
        # resultado — e a nota existe, então o que resta é dizer qual é.
        chave = _chave_do_corpo(corpo)
        return ResultadoProbe(
            veredito=Veredito.NOTA_GERADA,
            perfil=None,
            codigos=(),
            motivo=(
                f"O servidor ACEITOU a DPS do probe, que deveria ter sido recusada por "
                f"E0713. Uma NFS-e de teste foi gerada na série {SERIE_PROBE} e precisa "
                "ser cancelada à mão no Emissor Web — esta versão ainda não registra "
                "eventos. Reporte o caso: o estrago deliberado deixou de funcionar."
            ),
            chave_acesso=normalizar_chave(chave) if chave else "",
        )

    # ------------------------------------------------------------ consulta

    def consultar(self, chave: str) -> NotaFiscal:
        """`GET {SEFIN}/nfse/{chave}` — a NFS-e pela chave de acesso."""
        chave = normalizar_chave(chave)
        corpo = self._transporte.get_json(f"{self.bases.sefin}/nfse/{chave}")
        return self._nota_de(corpo, exigir_xml=True, chave_consultada=chave)

    def dps_foi_processada(self, identificador: str) -> bool:
        """`HEAD {SEFIN}/dps/{id}` — a DPS virou nota?

        Primeiro passo da recuperação de emissão ambígua (P8). Responde a qualquer
        certificado válido, sem exigir que ele seja ator da nota — é a diferença
        para o `GET`, que devolve a chave e por isso aplica sigilo fiscal.
        """
        return self._transporte.head(f"{self.bases.sefin}/dps/{_id_dps(identificador)}")

    def chave_por_dps(self, identificador: str) -> str | None:
        """`GET {SEFIN}/dps/{id}` — a chave de acesso da nota gerada por esta DPS.

        Devolve `None` quando a DPS não gerou nota (404). Segundo passo da
        recuperação de emissão ambígua.

        Por sigilo fiscal, a chave só vem se o certificado da conexão corresponder a
        um dos atores informados na DPS — prestador, tomador ou intermediário.
        """
        url = f"{self.bases.sefin}/dps/{_id_dps(identificador)}"
        try:
            corpo = self._transporte.get_json(url)
        except TransporteError as exc:
            if exc.status_code == 404:
                return None
            raise

        chave = _chave_do_corpo(corpo)
        if not chave:
            raise RespostaInvalidaError(f"{url} respondeu sem chave de acesso. Corpo: {corpo!r}")
        return normalizar_chave(chave)

    def baixar_danfse(self, chave: str) -> bytes:
        """`GET {ADN}/danfse/{chave}` — o PDF oficial da nota.

        Mora na **raiz do ADN**, não na SEFIN e não sob `/contribuintes`. É o único
        endpoint desta biblioteca que devolve binário em vez de JSON.
        """
        chave = normalizar_chave(chave)
        return self._transporte.get_bytes(f"{self.bases.adn}/danfse/{chave}")

    def consultar_convenio(self, codigo_municipio: str) -> Convenio:
        """O passo zero: o município aderiu ao Sistema Nacional?

        Município não conveniado não recebe DPS, e o erro que volta de uma emissão
        contra ele não diz que o problema é esse.
        """
        return consultar_convenio(self._transporte, self.bases, codigo_municipio)

    # -------------------------------------------------------------- interno

    def _nota_de(
        self,
        corpo: object,
        *,
        exigir_xml: bool,
        chave_consultada: str = "",
    ) -> NotaFiscal:
        if not isinstance(corpo, Mapping):
            raise RespostaInvalidaError(
                f"Esperado objeto JSON com a NFS-e; veio {type(corpo).__name__}: {corpo!r}"
            )

        chave = _chave_do_corpo(corpo) or chave_consultada
        if not chave:
            raise RespostaInvalidaError(
                f"Resposta 2xx sem chave de acesso — o contrato mudou. Chaves "
                f"presentes: {sorted(corpo)}"
            )

        codificado = primeiro_campo(corpo, CAMPO_NFSE, "nfseXml", "xml")
        if not codificado and exigir_xml:
            raise RespostaInvalidaError(
                f"Resposta 2xx sem o campo {CAMPO_NFSE}. Chaves presentes: {sorted(corpo)}"
            )

        return NotaFiscal(
            chave_acesso=normalizar_chave(chave),
            xml=de_gzip_b64(codificado) if codificado else b"",
            id_dps=primeiro_campo(corpo, "idDps", "idDPS", "id"),
            tipo_ambiente=primeiro_campo(corpo, "tipoAmbiente", "tpAmb"),
            versao_aplicativo=primeiro_campo(corpo, "versaoAplicativo", "verAplic"),
            processada_em=primeiro_campo(corpo, "dataHoraProcessamento", "dhProc"),
            alertas=_alertas_de(corpo),
            dados=dict(corpo),
        )

    # ------------------------------------------------------- ciclo de vida

    def close(self) -> None:
        """Fecha o transporte, se este objeto for o dono dele."""
        if self._proprio:
            self._transporte.close()

    def __enter__(self) -> NFSeClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _id_dps(identificador: str) -> str:
    """Confere o identificador da DPS antes de gastar uma ida à rede."""
    limpo = identificador.strip().upper()
    if not (limpo.startswith("DPS") and len(limpo) == 45 and limpo[3:].isdigit()):
        raise DadosInvalidosError(
            f"Identificador de DPS tem 45 posições e começa com 'DPS'; recebi "
            f"{identificador!r}. Use `dps.identificador`."
        )
    return limpo


def _chave_do_corpo(corpo: object) -> str:
    if not isinstance(corpo, Mapping):
        return ""
    return primeiro_campo(corpo, "chaveAcesso", "chave", "chNFSe")


def _alertas_de(corpo: Mapping[str, Any]) -> tuple[MensagemSefin, ...]:
    """Avisos numa resposta de sucesso.

    Sai **só** do campo de alertas, nunca de `normalizar_mensagens` aplicada ao corpo
    inteiro. Aquela função, quando não acha lista de erro, cai no formato legado e
    lê a raiz como se fosse uma mensagem: um `motivo` ou `descricao` no topo de uma
    resposta bem-sucedida viraria alerta espúrio em toda emissão. Com o contrato
    instável de P11, é uma questão de tempo até um campo desses aparecer.

    O reempacote em `{"alertas": ...}` é para reaproveitar a tolerância de forma —
    lista, objeto único, capitalização variada — sem herdar o caminho legado.
    """
    for nome in ("alertas", "Alertas", "avisos", "Avisos"):
        if nome in corpo:
            return normalizar_mensagens({"alertas": corpo[nome]})
    return ()
