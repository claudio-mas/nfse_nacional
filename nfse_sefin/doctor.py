"""`nfse-doctor` — diagnóstico antes da primeira emissão.

Hoje, um dev que precisa emitir NFS-e não descobre que o município do cliente não
aderiu, que o certificado venceu, ou que o handshake mTLS não fecha, até a primeira
requisição voltar com um erro que não explica nada. Cada uma dessas falhas custa
horas porque a mensagem que volta não aponta a causa.

Este comando responde as quatro perguntas de uma vez, em ordem de custo crescente, e
para na primeira que falhar — não adianta consultar convênio se o certificado nem
abriu.

    $ nfse-doctor --pfx empresa.pfx --municipio 3304557
    $ nfse-doctor --pfx empresa.pfx --municipio 3304557 --servico "banho e tosa"

O código de saída é distinto por causa, para que script de implantação consiga
decidir o que fazer sem parsear texto.

`--probe-assinatura` acrescenta a quinta pergunta, que é a única cuja resposta não está
em documento nenhum: **qual par de versão e algoritmo este servidor aceita.** Ele manda
uma DPS estragada de propósito, que é sempre recusada, e lê a resposta pela camada em que
a recusa aconteceu — ver `probe.py`. Não gera nota, e recusa rodar em produção.
"""

from __future__ import annotations

import argparse
import getpass
import os
import ssl
import sys
from collections.abc import Callable, Sequence
from enum import IntEnum
from pathlib import Path
from typing import TextIO

from nfse_sefin import __version__
from nfse_sefin.ambientes import Ambiente, bases_de
from nfse_sefin.catalogos import buscar_servico
from nfse_sefin.cert import Certificate
from nfse_sefin.client import NFSeClient
from nfse_sefin.convenio import consultar_convenio, valida_codigo_ibge
from nfse_sefin.errors import (
    CertificadoIlegivelError,
    DadosInvalidosError,
    NFSeError,
    ProbeEmProducaoError,
    TransporteError,
)
from nfse_sefin.perfis import PERFIL_PADRAO
from nfse_sefin.probe import Veredito, recusar_producao
from nfse_sefin.transport import Transporte

__all__ = ["CodigoSaida", "main"]


class CodigoSaida(IntEnum):
    """Códigos de saída do `nfse-doctor`.

    Distintos por causa de propósito: um script de implantação decide o que fazer
    sem precisar interpretar a saída de texto. O 2 fica de fora porque o `argparse`
    já o usa para erro de uso.
    """

    SUCESSO = 0
    ERRO_INESPERADO = 1
    PKCS12_ILEGIVEL = 3
    CERTIFICADO_INVALIDO = 4
    MTLS_FALHOU = 5
    MUNICIPIO_NAO_ADERENTE = 6
    ARGUMENTO_INVALIDO = 7
    PROBE_INDETERMINADO = 8
    PROBE_GEROU_NOTA = 9
    PROBE_PERFIL_NAO_PADRAO = 10
    """O probe respondeu, e a resposta **não** é o padrão da biblioteca.

    Não é falha: é diagnóstico bem-sucedido com uma ação pendente. Merece código próprio
    porque `0` faria um script de implantação registrar tudo certo e só descobrir na
    primeira emissão que `NFSeClient(cert)` usa o perfil errado para este servidor.
    """


_OK = "OK  "
_FALHA = "FALHA"
_AVISO = "AVISO"


def _e_falha_de_tls(excecao: BaseException) -> bool:
    """Separa "o TLS não fechou" de "o servidor respondeu alguma coisa".

    Vale a distinção: certificado recusado no handshake e servidor fora do ar levam a
    ações completamente diferentes, e a exceção de rede sozinha não diz qual é.
    """
    atual: BaseException | None = excecao
    while atual is not None:
        if isinstance(atual, ssl.SSLError | ssl.SSLCertVerificationError):
            return True
        if "SSL" in type(atual).__name__ or "certificate" in str(atual).lower():
            return True
        atual = atual.__cause__ or atual.__context__
    return False


def _senha_do_pfx(argumentos: argparse.Namespace) -> str:
    """Senha por argumento, variável de ambiente, ou prompt.

    A ordem é deliberada: `--senha` na linha de comando é cômodo mas vaza para o
    histórico do shell e para `ps`, então o prompt é o padrão.
    """
    if argumentos.senha is not None:
        return str(argumentos.senha)
    do_ambiente = os.environ.get("NFSE_PFX_SENHA")
    if do_ambiente is not None:
        return do_ambiente
    return getpass.getpass("Senha do certificado: ")


def _rodar_probe(
    argumentos: argparse.Namespace,
    certificado: Certificate,
    ambiente: Ambiente,
    transporte: Transporte,
    linha: Callable[[str, str], None],
    saida: TextIO,
) -> CodigoSaida:
    """Pergunta ao servidor qual perfil ele aceita e relata. Não emite nota.

    Convênio **não** é pré-requisito: o probe classifica por camada de recusa, e
    município não aderente responde com código de negócio — que já é a resposta.
    """
    # Sem `with`: o transporte é injetado, então `NFSeClient.close()` não faz nada e quem
    # é dono dele é o `with Transporte(...)` de `_diagnosticar`. Um `with` aqui sugeriria
    # posse que este objeto não tem, e convidaria alguém a implementá-la — fechando a
    # conexão por baixo dos passos que ainda vêm depois.
    cliente = NFSeClient(certificado, ambiente=ambiente, transporte=transporte)
    try:
        resultado = cliente.probe_assinatura(argumentos.municipio)
    except DadosInvalidosError as exc:
        # O probe parou antes de mandar qualquer coisa: certificado que não é
        # e-CNPJ, ou o estrago deliberado que não pôde ser aplicado.
        linha(_FALHA, "o probe não pôde ser montado")
        print(f"\n  {exc}", file=saida)
        return CodigoSaida.ARGUMENTO_INVALIDO
    except TransporteError as exc:
        linha(_FALHA, "o probe não chegou a uma resposta")
        print(f"\n  {exc}", file=saida)
        return CodigoSaida.ERRO_INESPERADO
    except NFSeError as exc:
        # `AssinaturaError` e `RespostaInvalidaError` são irmãs das duas acima e não
        # descendem de nenhuma delas. Sem esta cláusula elas sobem como traceback de um
        # comando cujo contrato inteiro é linha rotulada e código de saída distinto.
        linha(_FALHA, f"o probe falhou: {type(exc).__name__}")
        print(f"\n  {exc}", file=saida)
        return CodigoSaida.ERRO_INESPERADO

    if resultado.veredito is Veredito.PERFIL_ENCONTRADO:
        assert resultado.perfil is not None  # garantido pelo veredito
        linha(_OK, f"perfil de assinatura aceito: {resultado.perfil.nome}")
        print(f"\n  {resultado.motivo}", file=saida)
        if resultado.perfil is PERFIL_PADRAO:
            return CodigoSaida.SUCESSO

        # O padrão da biblioteca não serve neste servidor. Emitir sem passar `perfil=`
        # vai falhar, então dizer só isso no texto não basta: um script de implantação lê
        # o código de saída, e é para isso que `CodigoSaida` existe.
        print(
            "\n  Este NÃO é o perfil padrão da biblioteca "
            f"({PERFIL_PADRAO.nome}). Emitir sem configurar vai falhar."
            "\n\n  No código:"
            "\n    from nfse_sefin import NFSeClient, por_nome"
            f"\n    cliente = NFSeClient(cert, perfil=por_nome({resultado.perfil.nome!r}))",
            file=saida,
        )
        return CodigoSaida.PROBE_PERFIL_NAO_PADRAO

    if resultado.veredito is Veredito.NOTA_GERADA:
        linha(_FALHA, "o probe gerou uma NFS-e — não deveria")
        print(f"\n  {resultado.motivo}", file=saida)
        if resultado.chave_acesso:
            print(f"\n  Chave a cancelar: {resultado.chave_acesso}", file=saida)
        elif resultado.id_dps:
            # Sem chave no corpo, o identificador da DPS é o que ainda acha a nota.
            print(
                "\n  A resposta não trouxe a chave. Ache a nota pela DPS:"
                f"\n    cliente.chave_por_dps({resultado.id_dps!r})",
                file=saida,
            )
        return CodigoSaida.PROBE_GEROU_NOTA

    linha(_AVISO, "o probe não conseguiu decidir o perfil")
    print(f"\n  {resultado.motivo}", file=saida)
    return CodigoSaida.PROBE_INDETERMINADO


def _diagnosticar(argumentos: argparse.Namespace, saida: TextIO) -> CodigoSaida:
    def linha(marca: str, texto: str) -> None:
        print(f"  [{marca}] {texto}", file=saida)

    # Os `choices` do argparse são exatamente os valores do enum, então converter
    # direto elimina um if/else que erra em silêncio quando alguém acrescenta um
    # ambiente novo.
    ambiente = Ambiente(argumentos.ambiente)
    bases = bases_de(ambiente)

    print(f"nfse-doctor {__version__} — ambiente: {ambiente.value}", file=saida)
    print(file=saida)

    # Antes de tudo, inclusive de abrir o certificado: o probe manda uma DPS de verdade,
    # e recusar cedo é o que garante que nada saia da máquina por engano.
    if argumentos.probe_assinatura:
        try:
            recusar_producao(ambiente)
        except ProbeEmProducaoError as exc:
            linha(_FALHA, str(exc))
            return CodigoSaida.ARGUMENTO_INVALIDO

    # ------------------------------------------------- 1. o arquivo abre?
    caminho = Path(argumentos.pfx)
    if not caminho.is_file():
        linha(_FALHA, f"certificado não encontrado: {caminho}")
        return CodigoSaida.ARGUMENTO_INVALIDO

    try:
        certificado = Certificate.from_pfx(caminho, _senha_do_pfx(argumentos))
    except CertificadoIlegivelError as exc:
        linha(_FALHA, "não foi possível abrir o certificado")
        print(file=saida)
        print(f"  {exc}", file=saida)
        return CodigoSaida.PKCS12_ILEGIVEL

    linha(_OK, f"certificado aberto: {certificado.cn}")
    if certificado.usa_cifras_legadas:
        linha(
            _AVISO,
            "o .pfx usa cifras PKCS#12 legadas; funciona aqui, mas pode falhar em "
            "build ligada ao OpenSSL do sistema sem legacy provider",
        )

    # -------------------------------------------------- 2. está na validade?
    dias = certificado.dias_para_vencer
    if certificado.vencido:
        linha(_FALHA, f"certificado fora da validade (vence em {certificado.validade:%Y-%m-%d})")
        return CodigoSaida.CERTIFICADO_INVALIDO
    if certificado.precisa_renovar:
        linha(_AVISO, f"certificado vence em {dias} dias ({certificado.validade:%Y-%m-%d})")
    else:
        linha(_OK, f"certificado válido por mais {dias} dias")

    # ---------------------------------------- 3. o município tem formato válido?
    if not valida_codigo_ibge(argumentos.municipio):
        linha(_FALHA, f"código IBGE deve ter 7 dígitos; recebido {argumentos.municipio!r}")
        return CodigoSaida.ARGUMENTO_INVALIDO

    # ----------------------------------------- 4. o mTLS fecha e o município aderiu?
    #
    # `tentativas=1`: diagnóstico quer o primeiro erro, limpo. Handshake recusado não
    # melhora na segunda tentativa — o certificado não vira válido — e o retry ainda
    # troca a `SSLError` original pela falha da última tentativa, que é justamente a
    # informação que este comando existe para dar.
    with Transporte(certificado, tentativas=1) as transporte:
        try:
            convenio = consultar_convenio(transporte, bases, argumentos.municipio)
        except TransporteError as exc:
            if _e_falha_de_tls(exc):
                linha(_FALHA, "handshake mTLS não fechou")
                print(file=saida)
                print(f"  {exc}", file=saida)
                print(
                    "\n  O servidor recusou o certificado na conexão. Confira se o A1 é "
                    "\n  ICP-Brasil e se está dentro da validade.",
                    file=saida,
                )
                return CodigoSaida.MTLS_FALHOU
            linha(_FALHA, f"consulta de convênio falhou: {exc}")
            return CodigoSaida.ERRO_INESPERADO

        linha(_OK, "handshake mTLS fechou")

        if not convenio.aderido:
            linha(_FALHA, f"município {argumentos.municipio} não aderiu ao Sistema Nacional")
            print(
                "\n  Município sem convênio não recebe DPS. Se ele tem sistema próprio,"
                "\n  a emissão continua no sistema dele, não aqui.",
                file=saida,
            )
        else:
            linha(_OK, f"município {argumentos.municipio} aderiu ao Sistema Nacional")
            linha(_OK, f"rota de convênio que respondeu: {convenio.caminho}")

        # ------------------------------------------- 5. qual assinatura o servidor aceita?
        codigo_do_probe = CodigoSaida.SUCESSO
        if argumentos.probe_assinatura:
            codigo_do_probe = _rodar_probe(
                argumentos, certificado, ambiente, transporte, linha, saida
            )

        # Município não aderente vence o resultado do probe: sem convênio não se emite de
        # jeito nenhum, e configurar o perfil certo não muda isso. O probe já relatou o
        # que descobriu no texto — o código de saída fica com o bloqueio mais duro.
        if not convenio.aderido:
            return CodigoSaida.MUNICIPIO_NAO_ADERENTE
        if codigo_do_probe is not CodigoSaida.SUCESSO:
            return codigo_do_probe

    # ------------------------------------------------------ 6. bônus: o serviço
    if argumentos.servico:
        achados = buscar_servico(argumentos.servico)
        if not achados:
            linha(_AVISO, f"nenhum serviço da lista nacional casa com {argumentos.servico!r}")
        else:
            linha(_OK, f"{len(achados)} serviço(s) para {argumentos.servico!r}:")
            for servico in achados[:10]:
                print(f"         cTribNac {servico.codigo}  {servico.descricao}", file=saida)
            if len(achados) > 10:
                print(f"         ... e mais {len(achados) - 10}", file=saida)

    print("\nTudo pronto para emitir.", file=saida)
    return CodigoSaida.SUCESSO


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(
        prog="nfse-doctor",
        description="Diagnostica certificado, conexão mTLS e convênio municipal "
        "antes da primeira emissão de NFS-e.",
        epilog="A senha do certificado pode vir de --senha, da variável "
        "NFSE_PFX_SENHA, ou do prompt. Prefira o prompt: --senha fica no "
        "histórico do shell e aparece em `ps`.",
    )
    analisador.add_argument("--pfx", required=True, help="caminho do certificado A1 (.pfx/.p12)")
    analisador.add_argument("--municipio", required=True, help="código IBGE de 7 dígitos")
    analisador.add_argument("--senha", default=None, help="senha do .pfx (evite; use o prompt)")
    analisador.add_argument(
        "--ambiente",
        choices=tuple(a.value for a in Ambiente),
        default=Ambiente.PRODUCAO_RESTRITA.value,
        help=f"padrão: {Ambiente.PRODUCAO_RESTRITA.value}",
    )
    analisador.add_argument(
        "--servico",
        default=None,
        help="descrição do serviço, para descobrir o cTribNac correspondente",
    )
    analisador.add_argument(
        "--probe-assinatura",
        action="store_true",
        help="descobre qual perfil de assinatura o servidor aceita. Manda uma DPS "
        "estragada de propósito, que é sempre recusada — não gera nota. Só em "
        "produção restrita.",
    )
    analisador.add_argument("--version", action="version", version=f"nfse-doctor {__version__}")
    return analisador


def main(argv: Sequence[str] | None = None, saida: TextIO | None = None) -> int:
    """Ponto de entrada do console script `nfse-doctor`."""
    destino = saida if saida is not None else sys.stdout
    argumentos = _analisador().parse_args(argv)
    try:
        return int(_diagnosticar(argumentos, destino))
    except KeyboardInterrupt:  # pragma: no cover - interativo
        print("\nInterrompido.", file=destino)
        return int(CodigoSaida.ERRO_INESPERADO)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
