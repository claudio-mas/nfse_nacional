"""Testes da fachada — os dados puros, sem `nfelib`.

O `DESIGN.md` chama a fachada de "a única coisa que as libs MIT concorrentes não
têm". O que isso significa em teste concreto: quem escreve `Servico(codigo="010101")`
nunca deve precisar saber que o caminho real é `dps.infDPS.serv.cServ.cTribNac`, e
todo erro que dá para pegar sem rede tem de ser pego aqui, com o nome do campo que o
chamador escreveu.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from nfse_sefin.ambientes import Ambiente
from nfse_sefin.errors import DadosInvalidosError, NFSeError
from nfse_sefin.facade import (
    DPS,
    Endereco,
    OpcaoSimplesNacional,
    Prestador,
    RegimeApuracaoSN,
    Servico,
    TipoEmitente,
    Tomador,
    TotalTributos,
)

FUSO_BR = timezone(timedelta(hours=-3))

# O sample oficial `dps-simples.xml` da nfelib. Serve de gabarito para o
# identificador: se o nosso bater com o dele, a regra de 45 posições está certa.
CNPJ_DO_SAMPLE = "01761135000132"
MUNICIPIO_DO_SAMPLE = "1400159"
ID_DO_SAMPLE = "DPS140015920176113500013200900000000000000006"

# CPF sintético com dígito verificador válido.
CPF_VALIDO = "11144477735"


def prestador(**kwargs: object) -> Prestador:
    base: dict[str, object] = {"cnpj": CNPJ_DO_SAMPLE}
    base.update(kwargs)
    return Prestador(**base)  # type: ignore[arg-type]


def servico(**kwargs: object) -> Servico:
    base: dict[str, object] = {
        "codigo": "010101",
        "descricao": "Banho e tosa",
        "valor": "150.00",
        "municipio_prestacao": MUNICIPIO_DO_SAMPLE,
    }
    base.update(kwargs)
    return Servico(**base)  # type: ignore[arg-type]


def dps(**kwargs: object) -> DPS:
    base: dict[str, object] = {
        "prestador": prestador(simples_nacional=OpcaoSimplesNacional.MEI),
        "servico": servico(),
        "serie": "900",
        "numero": "6",
        "competencia": date(2022, 9, 28),
        "municipio_emissor": MUNICIPIO_DO_SAMPLE,
        "emitido_em": datetime(2022, 9, 28, 13, 50, 29, tzinfo=FUSO_BR),
    }
    base.update(kwargs)
    return DPS(**base)  # type: ignore[arg-type]


# ------------------------------------------------ a fachada não conhece a nfelib


def test_facade_nao_importa_nfelib() -> None:
    """A regra estrutural do `DESIGN.md`, verificada em vez de prometida.

    Roda em subprocesso porque a suíte inteira já importou `nfelib` por outros
    caminhos — checar `sys.modules` neste processo não provaria nada.
    """
    codigo = (
        "import sys; import nfse_sefin.facade; "
        "assert 'nfelib' not in sys.modules, sorted(m for m in sys.modules if 'nfelib' in m)"
    )
    resultado = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr


# ------------------------------------------------------------- o identificador


def test_identificador_bate_com_o_sample_oficial() -> None:
    """45 posições montadas na ordem que `E0004` exige.

    O gabarito é o `Id` do `dps-simples.xml` que a `nfelib` distribui, gerado pelo
    Emissor Web do governo. Bater com ele é a evidência mais forte disponível sem
    certificado real.
    """
    assert dps().identificador == ID_DO_SAMPLE
    assert len(ID_DO_SAMPLE) == 45


def test_identificador_zera_a_esquerda_serie_e_numero() -> None:
    """No elemento vai `900` e `6`; no identificador vai `00900` e 15 posições.

    Os dois campos aparecem duas vezes no documento com formas diferentes, e trocar
    uma pela outra é rejeição.
    """
    documento = dps(serie="1", numero="42")

    assert documento.serie == "1"
    assert documento.numero == "42"
    assert documento.identificador.endswith("00001" + "42".zfill(15))


def test_identificador_de_cpf_completa_com_zeros() -> None:
    """ "CPF completar com 000 à esquerda" — zero mesmo, não espaço.

    As posições: `DPS` (0-2), município (3-9), tipo de inscrição (10), inscrição
    federal (11-24).
    """
    documento = dps(
        prestador=prestador(cnpj=None, cpf=CPF_VALIDO, simples_nacional=OpcaoSimplesNacional.MEI)
    )

    assert documento.identificador[10] == "1"  # tipo de inscrição = CPF
    assert documento.identificador[11:25] == "000" + CPF_VALIDO
    assert len(documento.identificador) == 45


def test_identificador_marca_cnpj_com_dois() -> None:
    assert dps().identificador[10] == "2"
    assert dps().identificador[11:25] == CNPJ_DO_SAMPLE


# --------------------------------------------------------------- dhEmi e datas


def test_microssegundo_e_removido() -> None:
    """`TSDateTimeUTC` não tem casa de microssegundo.

    `datetime.now(tz).isoformat()` devolve `...:29.123456-03:00`, que o schema
    recusa. Descobrir isso pela rejeição custa uma emissão; aqui custa zero.
    """
    documento = dps(emitido_em=datetime(2022, 9, 28, 13, 50, 29, 123456, tzinfo=FUSO_BR))

    assert documento.emitido_em.microsecond == 0
    assert documento.emitido_em.isoformat() == "2022-09-28T13:50:29-03:00"


def test_datetime_sem_fuso_e_recusado() -> None:
    """O leiaute exige deslocamento explícito e não há padrão razoável a inventar."""
    with pytest.raises(DadosInvalidosError, match="fuso horário"):
        dps(emitido_em=datetime(2022, 9, 28, 13, 50, 29))


def test_fuso_com_minutos_quebrados_e_recusado() -> None:
    """O padrão do XSD fixa `±hh:00`. Fusos de meia hora não cabem no leiaute."""
    with pytest.raises(DadosInvalidosError, match="horas inteiras"):
        dps(emitido_em=datetime(2022, 9, 28, 13, 50, tzinfo=timezone(timedelta(minutes=330))))


def test_emitido_em_tem_padrao_utilizavel() -> None:
    """Sem `emitido_em`, a DPS usa agora com fuso local — e já sem microssegundo."""
    documento = DPS(
        prestador=prestador(simples_nacional=OpcaoSimplesNacional.MEI),
        servico=servico(),
        serie="1",
        numero="1",
        competencia=date(2026, 8, 17),
        municipio_emissor=MUNICIPIO_DO_SAMPLE,
    )
    assert documento.emitido_em.tzinfo is not None
    assert documento.emitido_em.microsecond == 0


# ------------------------------------------------------------ CPF, CNPJ, choice


def test_cnpj_com_pontuacao_e_normalizado() -> None:
    assert prestador(cnpj="01.761.135/0001-32").cnpj == CNPJ_DO_SAMPLE


@pytest.mark.parametrize("cnpj", ["01761135000133", "11111111111111", "123"])
def test_cnpj_invalido(cnpj: str) -> None:
    with pytest.raises(DadosInvalidosError):
        prestador(cnpj=cnpj)


@pytest.mark.parametrize("cpf", ["11144477730", "00000000000", "123"])
def test_cpf_invalido(cpf: str) -> None:
    with pytest.raises(DadosInvalidosError):
        prestador(cnpj=None, cpf=cpf)


def test_cnpj_e_cpf_juntos() -> None:
    """O leiaute usa `choice`: os dois juntos é rejeição."""
    with pytest.raises(DadosInvalidosError, match="exatamente um"):
        Prestador(cnpj=CNPJ_DO_SAMPLE, cpf=CPF_VALIDO)


def test_sem_cnpj_nem_cpf() -> None:
    with pytest.raises(DadosInvalidosError, match="exatamente um"):
        Prestador()


def test_tomador_exige_nome() -> None:
    """`toma/xNome` é obrigatório quando o tomador é identificado."""
    with pytest.raises(DadosInvalidosError, match="nome"):
        Tomador(cpf=CPF_VALIDO)


def test_tomador_com_nome_passa() -> None:
    assert Tomador(cpf=CPF_VALIDO, nome="Fulano").nome == "Fulano"


# ------------------------------------------------------------------- o serviço


def test_codigo_de_servico_no_formato_da_lc116_e_recusado() -> None:
    """P5: o campo real é `cTribNac`, seis dígitos — não `"01.01"`.

    Este é o erro que o esboço original do plano cometia, e a mensagem diz qual é a
    forma certa em vez de só reprovar.
    """
    with pytest.raises(DadosInvalidosError, match="010101"):
        servico(codigo="01.01")


def test_codigo_fora_da_lista_nacional() -> None:
    """P7: a existência na lista de 337 subitens é decidível offline."""
    with pytest.raises(DadosInvalidosError, match="lista nacional"):
        servico(codigo="999999")


def test_codigo_valido_normaliza() -> None:
    assert servico(codigo="010101").codigo == "010101"


def test_valor_aceita_str_int_e_decimal() -> None:
    """O campo é tipado `Decimal`; `str` e `int` são conveniência de runtime.

    O valor quase sempre vem de JSON ou de coluna de banco, e obrigar o chamador a
    converter só moveria o problema para fora da biblioteca.
    """
    assert servico(valor="150.00").valor == Decimal("150.00")
    assert servico(valor=150).valor == Decimal("150")
    assert servico(valor=Decimal("150.00")).valor == Decimal("150.00")


def test_valor_float_e_recusado() -> None:
    """`0.1 + 0.2 != 0.3`, e um centavo errado numa nota fiscal não é detalhe."""
    with pytest.raises(DadosInvalidosError, match="float"):
        servico(valor=150.0)


def test_valor_negativo() -> None:
    with pytest.raises(DadosInvalidosError, match="negativo"):
        servico(valor="-1")


def test_aliquota_acima_do_teto_do_xsd() -> None:
    """`pAliq` é `TSDec1V2` — um dígito inteiro. Teto 9,99%, e a LC 116 fixa 5%."""
    with pytest.raises(DadosInvalidosError, match="aliquota"):
        servico(aliquota="10")


def test_aliquota_no_teto_passa() -> None:
    assert servico(aliquota="5").aliquota == Decimal("5")


def test_codigo_interno_com_hifen_e_recusado() -> None:
    """`cIntContrib` é `[a-zA-Z0-9]{1,20}`: sem hífen, sem espaço, sem acento.

    Achado ao validar contra o XSD oficial, não ao ler o Anexo I — a coluna de
    tamanho do anexo diz só "20".
    """
    with pytest.raises(DadosInvalidosError, match="cIntContrib"):
        servico(codigo_interno="INT-1")


def test_codigo_interno_alfanumerico_passa() -> None:
    assert servico(codigo_interno="PED42").codigo_interno == "PED42"


def test_codigo_municipal_tem_tres_digitos() -> None:
    """`cTribMun` é `[0-9]{3}` — não é o código IBGE de 7."""
    with pytest.raises(DadosInvalidosError, match="cTribMun"):
        servico(codigo_municipal=MUNICIPIO_DO_SAMPLE)


# ------------------------------------------------------------ texto e endereço


def test_travessao_de_editor_de_texto_e_recusado() -> None:
    """`TSString` só aceita de `!` (0x21) a `ÿ` (0xFF).

    Travessão, aspas curvas e reticências saem de qualquer processador de texto e
    são rejeição de schema. Acentuação portuguesa passa — é o ponto do teste
    seguinte.
    """
    with pytest.raises(DadosInvalidosError, match="'!' a 'ÿ'"):
        prestador(nome="Petshop — Matriz")


def test_acentuacao_portuguesa_passa() -> None:
    assert prestador(nome="Ação Comércio Ltda").nome == "Ação Comércio Ltda"


def test_espaco_das_pontas_some() -> None:
    """O padrão de `TSString` proíbe espaço nas extremidades."""
    assert prestador(nome="  Petshop   Ltda  ").nome == "Petshop Ltda"


def test_telefone_vira_so_digitos() -> None:
    """`TSTelefone` é `[0-9]{6,20}` — parêntese e traço não passam."""
    assert prestador(telefone="(69) 3222-1234").telefone == "6932221234"


def test_telefone_curto_demais() -> None:
    with pytest.raises(DadosInvalidosError, match="6 a 20"):
        prestador(telefone="123")


def test_municipio_com_nome_em_vez_de_codigo() -> None:
    """O erro de preenchimento mais comum do grupo de endereço."""
    with pytest.raises(DadosInvalidosError, match="7 dígitos"):
        Endereco("Rua A", "10", "Centro", "Porto Velho", "76800000")


def test_endereco_completo() -> None:
    endereco = Endereco("Rua A", "10", "Centro", MUNICIPIO_DO_SAMPLE, "69.300-000")
    assert endereco.cep == "69300000"


# --------------------------------------------------- totTrib x Simples Nacional


def test_mei_tem_padrao() -> None:
    """MEI é o único regime com uma saída óbvia: declinar (Decreto 8.264/2014)."""
    documento = dps()
    total = documento.total_tributos
    assert total is not None
    assert total.ramo == "indTotTrib"


def test_me_epp_sem_percentual_falha_cedo() -> None:
    """ME/EPP precisa de um número que mora na contabilidade, não na biblioteca.

    Chutar zero aqui seria declarar tributo estimado de R$ 0,00 em nome do cliente.
    """
    with pytest.raises(DadosInvalidosError, match="pelo_simples_nacional"):
        dps(prestador=prestador(simples_nacional=OpcaoSimplesNacional.ME_EPP))


def test_nao_optante_sem_total_falha_cedo() -> None:
    with pytest.raises(DadosInvalidosError, match="por_valor"):
        dps(prestador=prestador(simples_nacional=OpcaoSimplesNacional.NAO_OPTANTE))


@pytest.mark.parametrize(
    ("regime", "total", "codigo"),
    [
        (OpcaoSimplesNacional.ME_EPP, TotalTributos.nao_informar(), "E0712"),
        (OpcaoSimplesNacional.NAO_OPTANTE, TotalTributos.nao_informar(), "E0713"),
        (
            OpcaoSimplesNacional.NAO_OPTANTE,
            TotalTributos.pelo_simples_nacional("6.00"),
            "E0713",
        ),
        (OpcaoSimplesNacional.MEI, TotalTributos.pelo_simples_nacional("6.00"), "E0710"),
    ],
)
def test_matriz_de_rejeicao_do_tottrib(
    regime: OpcaoSimplesNacional, total: TotalTributos, codigo: str
) -> None:
    """As três regras que o XSD não expressa, aplicadas antes de sair da máquina.

    O `xs:choice` do `totTrib` não sabe nada sobre `opSimpNac`, que mora em outro
    ramo da árvore. A ligação está só no Anexo I, como rejeição.
    """
    with pytest.raises(DadosInvalidosError, match=codigo):
        dps(
            prestador=prestador(simples_nacional=regime),
            servico=servico(total_tributos=total),
        )


@pytest.mark.parametrize(
    ("regime", "total"),
    [
        (OpcaoSimplesNacional.MEI, TotalTributos.nao_informar()),
        (OpcaoSimplesNacional.ME_EPP, TotalTributos.pelo_simples_nacional("6.00")),
        (OpcaoSimplesNacional.NAO_OPTANTE, TotalTributos.por_valor("10", "0", "5")),
        (OpcaoSimplesNacional.NAO_OPTANTE, TotalTributos.por_percentual("1.5", "0", "5")),
    ],
)
def test_combinacoes_permitidas_passam(regime: OpcaoSimplesNacional, total: TotalTributos) -> None:
    """O outro lado da matriz: provar que a guarda não recusa o que é válido."""
    documento = dps(
        prestador=prestador(simples_nacional=regime),
        servico=servico(total_tributos=total),
    )
    assert documento.total_tributos is total


def test_percentual_do_simples_acima_do_teto() -> None:
    """`pTotTribSN` é `TSDec2V2` — dois dígitos inteiros."""
    with pytest.raises(DadosInvalidosError, match="0 a 99.99"):
        TotalTributos.pelo_simples_nacional("100")


def test_percentual_por_esfera_acima_de_cem() -> None:
    """E0706, E0707, E0708."""
    with pytest.raises(DadosInvalidosError, match="0 a 100"):
        TotalTributos.por_percentual("101", "0", "0")


# ---------------------------------------------------------------- serie e nDPS


@pytest.mark.parametrize("serie", ["0", "000000", "", "abc"])
def test_serie_invalida(serie: str) -> None:
    with pytest.raises(DadosInvalidosError, match="serie"):
        dps(serie=serie)


@pytest.mark.parametrize("numero", ["0", "1234567890123456"])
def test_numero_invalido(numero: str) -> None:
    with pytest.raises(DadosInvalidosError, match="numero"):
        dps(numero=numero)


def test_serie_com_zero_a_esquerda_normaliza() -> None:
    """`<serie>` não aceita zero à esquerda; o identificador exige. A DPS separa."""
    documento = dps(serie="00900")
    assert documento.serie == "900"
    assert documento.identificador == ID_DO_SAMPLE


# --------------------------------------------------------------------- diversos


def test_versao_aplicacao_cabe_em_veraplic() -> None:
    """`TSVerAplic` aceita 20 caracteres, e o nosso padrão precisa caber."""
    assert len(dps().versao_aplicacao) <= 20


def test_versao_aplicacao_longa_demais() -> None:
    with pytest.raises(DadosInvalidosError, match="verAplic"):
        dps(versao_aplicacao="x" * 21)


def test_ambiente_padrao_e_o_conservador() -> None:
    """Padrão nunca é produção: emitir nota de verdade tem de ser escolha explícita."""
    assert dps().ambiente is Ambiente.PRODUCAO_RESTRITA


def test_tipo_emitente_padrao() -> None:
    assert dps().tipo_emitente is TipoEmitente.PRESTADOR


def test_dps_e_imutavel() -> None:
    with pytest.raises(AttributeError):
        dps().serie = "1"  # type: ignore[misc]


def test_erros_da_fachada_descem_de_nfse_error() -> None:
    """Quem integra captura `NFSeError` e pega tudo que é nosso."""
    with pytest.raises(NFSeError):
        servico(codigo="999999")


def test_regime_de_apuracao_sn_e_opcional() -> None:
    documento = dps(
        prestador=prestador(
            simples_nacional=OpcaoSimplesNacional.ME_EPP,
            regime_apuracao_sn=RegimeApuracaoSN.FEDERAIS_E_MUNICIPAL_PELO_SN,
        ),
        servico=servico(total_tributos=TotalTributos.pelo_simples_nacional("6.00")),
    )
    assert documento.prestador.regime_apuracao_sn is RegimeApuracaoSN.FEDERAIS_E_MUNICIPAL_PELO_SN
