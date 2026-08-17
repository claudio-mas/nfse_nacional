"""Transporte HTTP: mTLS, envelope JSON, gzip+base64, retry e erros normalizados.

Concentra tudo que é sobre *falar* com o Sistema Nacional, para que os módulos de
negócio não precisem saber que o XML viaja comprimido dentro de um campo de JSON.

## Retry só em leitura

`POST /nfse` é escrita fiscal síncrona e **não idempotente**. Se a resposta se perde
num timeout depois de o servidor ter processado, repetir a requisição não é
"tentar de novo": é tentar emitir a mesma nota duas vezes, e a segunda volta
rejeitada por série+número+município+CNPJ repetidos.

Por isso o retry aqui é ligado por método, não por status: `GET` e `HEAD` repetem,
`POST` nunca. Em falha ambígua de emissão o caminho é consultar — `HEAD /dps/{id}`
diz se a DPS foi processada, e `GET /dps/{id}` devolve a chave de acesso.

## Erro não tem forma estável

Foram observados quatro formatos em produção, com capitalização variável. Um parser
que assume um só quebra em campo, e o usuário recebe `KeyError` em vez do motivo da
rejeição. `normalizar_mensagens` aceita todos e nunca levanta.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import httpx

from nfse_sefin.cert import Certificate
from nfse_sefin.errors import (
    MensagemSefin,
    RespostaInvalidaError,
    TransporteError,
)

__all__ = [
    "Transporte",
    "gzip_b64",
    "de_gzip_b64",
    "normalizar_mensagens",
    "primeiro_campo",
    "METODOS_COM_RETRY",
    "TIMEOUT_PADRAO",
]

logger = logging.getLogger("nfse_sefin")

METODOS_COM_RETRY = frozenset({"GET", "HEAD"})
"""P8. `POST` fica de fora: emissão não é idempotente."""

TIMEOUT_PADRAO = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
"""Recepção fiscal é lenta em horário de pico; 60s de leitura não é exagero."""

_TAMANHO_MAXIMO_CORPO_NO_ERRO = 2000
"""O suficiente para diagnosticar sem despejar um HTML de proxy inteiro no log."""


# --------------------------------------------------------------- gzip+base64


def gzip_b64(dados: bytes) -> str:
    """XML assinado → gzip → base64, que é como todo XML viaja nesta API.

    `mtime=0` deixa a saída determinística. Não é exigência do servidor; é para que
    o mesmo XML produza sempre o mesmo payload, o que torna teste e diff legíveis.
    """
    return base64.b64encode(gzip.compress(dados, mtime=0)).decode("ascii")


def de_gzip_b64(valor: str) -> bytes:
    """O caminho inverso, para os campos de XML que voltam na resposta."""
    # `gzip.decompress(b"")` devolve `b""` em silêncio, sem levantar. Sem esta
    # guarda, um campo vazio na resposta viraria "XML vazio" em vez de erro, e o
    # problema só apareceria muito depois, num parse que não explica nada.
    if not valor:
        raise RespostaInvalidaError("Campo de XML veio vazio; esperado gzip+base64.")
    try:
        bruto = gzip.decompress(base64.b64decode(valor, validate=True))
    except (binascii.Error, gzip.BadGzipFile, OSError, ValueError) as exc:
        raise RespostaInvalidaError(
            f"Campo deveria ser XML em gzip+base64 e não pôde ser decodificado: {exc}"
        ) from exc
    if not bruto:
        raise RespostaInvalidaError("Campo de XML descomprimiu para conteúdo vazio.")
    return bruto


# ----------------------------------------------------- normalização de erro


def _texto(valor: object) -> str:
    if valor is None:
        return ""
    return valor if isinstance(valor, str) else str(valor)


def primeiro_campo(origem: Mapping[str, Any], *nomes: str) -> str:
    """Primeiro nome presente, testando também a inicial maiúscula.

    A API mistura `codigo` e `Codigo` entre endpoints, e mistura `descricao` com
    `mensagem` entre o formato atual e o legado. Público porque `client.py` lê os
    campos de resposta com a mesma tolerância — `chaveAcesso` e `ChaveAcesso` já
    foram vistos nos dois endpoints que a devolvem.
    """
    for nome in nomes:
        for variante in (nome, nome.capitalize(), nome.upper()):
            if variante in origem:
                texto = _texto(origem[variante])
                if texto:
                    return texto
    return ""


def _mensagem_de(item: object) -> MensagemSefin | None:
    if isinstance(item, str):
        return MensagemSefin(codigo="", descricao=item) if item else None
    if not isinstance(item, Mapping):
        return None
    mensagem = MensagemSefin(
        codigo=primeiro_campo(item, "codigo", "code"),
        descricao=primeiro_campo(item, "descricao", "mensagem", "message", "motivo"),
        complemento=primeiro_campo(item, "complemento", "detalhe", "parametros"),
    )
    if not (mensagem.codigo or mensagem.descricao or mensagem.complemento):
        return None
    return mensagem


def normalizar_mensagens(corpo: object) -> tuple[MensagemSefin, ...]:
    """Achata qualquer um dos formatos de erro conhecidos numa lista única.

    Aceita, e todos foram vistos em produção:

    - `{"erro": [{codigo, descricao, complemento}, ...]}`
    - `{"erros": [...]}`
    - uma lista nua no topo
    - o legado `{"codigo": ..., "mensagem": ...}`

    Mais as variações de capitalização e o caso de `erro` vir como objeto único em
    vez de lista. Nunca levanta: corpo irreconhecível devolve tupla vazia, porque
    quem chama já está tratando um erro e não pode receber outro por cima.
    """
    if isinstance(corpo, list):
        return tuple(m for m in (_mensagem_de(i) for i in corpo) if m is not None)

    if not isinstance(corpo, Mapping):
        return ()

    for chave in ("erro", "erros", "Erro", "Erros", "alertas", "Alertas"):
        if chave not in corpo:
            continue
        conteudo = corpo[chave]
        if isinstance(conteudo, list):
            achadas = tuple(m for m in (_mensagem_de(i) for i in conteudo) if m is not None)
        else:
            unica = _mensagem_de(conteudo)
            achadas = (unica,) if unica is not None else ()
        if achadas:
            return achadas

    # Formato legado: o próprio corpo é a mensagem.
    unica = _mensagem_de(corpo)
    return (unica,) if unica is not None else ()


# ------------------------------------------------------------------ cliente


class Transporte:
    """Cliente HTTP com mTLS, retry de leitura e erros normalizados.

    Sem estado mutável por requisição: uma instância serve várias threads, que é o
    que a restrição de thread-safety do projeto exige.
    """

    def __init__(
        self,
        certificate: Certificate,
        *,
        timeout: httpx.Timeout | float = TIMEOUT_PADRAO,
        tentativas: int = 3,
        espera_base: float = 1.5,
        client: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        """
        Args:
            certificate: certificado A1 já carregado; vira o contexto TLS cliente.
            timeout: repassado ao `httpx`.
            tentativas: total de tentativas em GET/HEAD, incluindo a primeira.
            espera_base: segundos da primeira espera; dobra a cada tentativa.
            client: injeta um `httpx.Client` pronto. Só para teste.
            dormir: injeta o `sleep`. Só para teste, para o retry não custar tempo.
        """
        if tentativas < 1:
            raise ValueError("tentativas tem de ser pelo menos 1")

        self._tentativas = tentativas
        self._espera_base = espera_base
        self._dormir = dormir
        self._proprio = client is None
        # O contexto TLS é montado uma vez, na construção. Montar por requisição
        # multiplicaria as idas da chave privada ao disco sem ganho nenhum.
        self._client = client or httpx.Client(
            verify=certificate.ssl_context(),
            timeout=timeout,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

    # -------------------------------------------------------------- verbos

    def get_json(self, url: str) -> Any:
        return self._json(self._request("GET", url))

    def get_bytes(self, url: str) -> bytes:
        """Para o DANFSe, que devolve PDF binário em vez de JSON."""
        return self._request("GET", url).content

    def head(self, url: str) -> bool:
        """`True` se o recurso existe (200), `False` se não (404).

        `HEAD /dps/{id}` é o primeiro passo da recuperação de emissão ambígua: diz se
        a DPS foi processada sem custar o corpo da resposta.
        """
        resposta = self._request("HEAD", url, status_esperados=(200, 404))
        return resposta.status_code == 200

    def post_json(self, url: str, payload: Mapping[str, Any]) -> Any:
        """POST com envelope JSON. **Nunca** repete — ver P8 no topo do módulo."""
        return self._json(self._request("POST", url, json=payload))

    # ------------------------------------------------------------ interno

    def _request(
        self,
        metodo: str,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        status_esperados: Iterable[int] = (),
    ) -> httpx.Response:
        tentativas = self._tentativas if metodo in METODOS_COM_RETRY else 1
        ultima_falha: Exception | None = None

        for tentativa in range(1, tentativas + 1):
            try:
                resposta = self._client.request(metodo, url, json=json)
            except httpx.HTTPError as exc:
                ultima_falha = exc
                if tentativa == tentativas:
                    break
                self._esperar(metodo, url, tentativa, f"{type(exc).__name__}: {exc}")
                continue

            if resposta.status_code in status_esperados:
                return resposta
            if resposta.status_code < 400:
                return resposta

            # 5xx é instabilidade do servidor e vale repetir — mas só onde repetir é
            # seguro. 4xx é decisão do servidor sobre esta requisição: repetir
            # devolve o mesmo erro e só atrasa o diagnóstico.
            repetivel = resposta.status_code >= 500 and metodo in METODOS_COM_RETRY
            if not repetivel or tentativa == tentativas:
                raise self._erro_http(metodo, url, resposta)
            self._esperar(metodo, url, tentativa, f"HTTP {resposta.status_code}")

        raise TransporteError(
            f"{metodo} {url} falhou após {tentativas} tentativa(s): {ultima_falha}",
            metodo=metodo,
            url=url,
        ) from ultima_falha

    def _esperar(self, metodo: str, url: str, tentativa: int, motivo: str) -> None:
        espera = self._espera_base * (2 ** (tentativa - 1))
        logger.warning(
            "%s %s tentativa %d falhou (%s); repetindo em %.1fs",
            metodo,
            url,
            tentativa,
            motivo,
            espera,
        )
        self._dormir(espera)

    @staticmethod
    def _erro_http(metodo: str, url: str, resposta: httpx.Response) -> TransporteError:
        try:
            corpo: object = resposta.json()
        except ValueError:
            corpo = None

        mensagens: Sequence[MensagemSefin] = ()
        if corpo is not None:
            mensagens = normalizar_mensagens(corpo)
        detalhe = "; ".join(str(m) for m in mensagens) if mensagens else ""

        return TransporteError(
            f"{metodo} {url} devolveu HTTP {resposta.status_code}"
            + (f": {detalhe}" if detalhe else ""),
            status_code=resposta.status_code,
            mensagens=mensagens,
            corpo=resposta.text[:_TAMANHO_MAXIMO_CORPO_NO_ERRO],
            metodo=metodo,
            url=url,
        )

    @staticmethod
    def _json(resposta: httpx.Response) -> Any:
        if not resposta.content:
            return {}
        try:
            return resposta.json()
        except ValueError as exc:
            raise RespostaInvalidaError(
                f"Resposta {resposta.status_code} não é JSON: "
                f"{resposta.text[:_TAMANHO_MAXIMO_CORPO_NO_ERRO]!r}"
            ) from exc

    # ------------------------------------------------------------ ciclo de vida

    def close(self) -> None:
        """Fecha o `httpx.Client`, se este objeto for o dono dele."""
        if self._proprio:
            self._client.close()

    def __enter__(self) -> Transporte:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
