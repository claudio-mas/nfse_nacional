"""Lista nacional de serviços da LC 116/2003, com o código de tributação nacional.

ARQUIVO GERADO. Não edite à mão — rode `python tools/gerar_catalogo_servicos.py`.
Fonte: seção `MUN.INCID_INFO.SERV.` de `anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md`.

São 337 subitens. **118 deles precisaram de `zfill(6)`**: a tabela do anexo
saiu de um Excel que tratou a coluna de código como número e comeu o zero à esquerda,
então o anexo diz `10101` onde o `cTribNac` real é `010101`. O XSD é a autoridade e fixa
`[0-9]{6}`, com 2 dígitos de item, 2 de subitem e 2 de desdobro nacional.

Colunas de localidade de incidência (EP/LP/ET/EDEmit) não são capturadas: o significado
delas depende de notas de rodapé do anexo que este gerador não interpreta, e um mapeamento
errado seria pior que a ausência. A coluna de grupo obrigatório é capturada porque é
inequívoca — `obra` ou `atvEvento`, e nada mais.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["Servico", "SERVICOS", "por_codigo", "buscar_servico", "TOTAL_DE_SERVICOS"]


@dataclass(frozen=True, slots=True)
class Servico:
    """Um subitem da lista nacional."""

    codigo: str
    """`cTribNac`: exatamente 6 dígitos."""

    descricao: str
    """Texto do desdobro nacional, como no anexo."""

    grupo_obrigatorio: str | None
    """Grupo que a DPS precisa trazer para este serviço: `obra`, `atvEvento`, ou nada."""

    @property
    def item(self) -> str:
        """Item da LC 116/2003 — os 2 primeiros dígitos."""
        return self.codigo[:2]

    @property
    def subitem(self) -> str:
        """Subitem da LC 116/2003 — dígitos 3 e 4."""
        return self.codigo[2:4]

    @property
    def desdobro(self) -> str:
        """Desdobro nacional — dígitos 5 e 6."""
        return self.codigo[4:]

    @property
    def rotulo_lc116(self) -> str:
        """A notação que aparece em texto corrido: `01.01.01`."""
        return f"{self.item}.{self.subitem}.{self.desdobro}"


_S = Servico

SERVICOS: tuple[Servico, ...] = (
    _S('010101', 'Análise e desenvolvimento de sistemas.', None),
    _S('010201', 'Programação.', None),
    _S('010301', 'Processamento de dados, textos, imagens, vídeos, páginas eletrônicas, aplicativos e sistemas de informação, entre outros formatos, e congêneres.', None),
    _S('010302', 'Armazenamento ou hospedagem de dados, textos, imagens, vídeos, páginas eletrônicas, aplicativos e sistemas de informação, entre outros formatos, e congêneres.', None),
    _S('010401', 'Elaboração de programas de computadores, inclusive de jogos eletrônicos, independentemente da arquitetura construtiva da máquina em que o programa será executado, incluindo tablets, smartphones e congêneres.', None),
    _S('010501', 'Licenciamento ou cessão de direito de uso de programas de computação.', None),
    _S('010601', 'Assessoria e consultoria em informática.', None),
    _S('010701', 'Suporte técnico em informática, inclusive instalação, configuração e manutenção de programas de computação e bancos de dados.', None),
    _S('010801', 'Planejamento, confecção, manutenção e atualização de páginas eletrônicas.', None),
    _S('010901', 'Disponibilização, sem cessão definitiva, de conteúdos de áudio por meio da internet (exceto a distribuição de conteúdos pelas prestadoras de Serviço de Acesso Condicionado, de que trata a Lei nº 12.485, de 12 de setembro de 2011, sujeita ao ICMS).', None),
    _S('010902', 'Disponibilização, sem cessão definitiva, de conteúdos de vídeo, imagem e texto por meio da internet, respeitada a imunidade de livros, jornais e periódicos (exceto a distribuição de conteúdos pelas prestadoras de Serviço de Acesso Condicionado, de que trata a Lei nº 12.485, de 12 de setembro de 2011, sujeita ao ICMS).', None),
    _S('020101', 'Serviços de pesquisas e desenvolvimento de qualquer natureza.', None),
    _S('030201', 'Cessão de direito de uso de marcas e de sinais de propaganda.', None),
    _S('030301', 'Exploração de salões de festas, centro de convenções, stands e congêneres, para realização de eventos ou negócios de qualquer natureza.', None),
    _S('030302', 'Exploração de escritórios virtuais e congêneres, para realização de eventos ou negócios de qualquer natureza.', None),
    _S('030303', 'Exploração de quadras esportivas, estádios, ginásios, canchas e congêneres, para realização de eventos ou negócios de qualquer natureza.', None),
    _S('030304', 'Exploração de auditórios, casas de espetáculos e congêneres, para realização de eventos ou negócios de qualquer natureza.', None),
    _S('030305', 'Exploração de parques de diversões e congêneres, para realização de eventos ou negócios de qualquer natureza.', None),
    _S('030401', 'Locação, sublocação, arrendamento, direito de passagem ou permissão de uso, compartilhado ou não, de ferrovia.', None),
    _S('030402', 'Locação, sublocação, arrendamento, direito de passagem ou permissão de uso, compartilhado ou não, de rodovia.', None),
    _S('030403', 'Locação, sublocação, arrendamento, direito de passagem ou permissão de uso, compartilhado ou não, de postes, cabos, dutos e condutos de qualquer natureza.', None),
    _S('030501', 'Cessão de andaimes, palcos, coberturas e outras estruturas de uso temporário.', None),
    _S('040101', 'Medicina.', None),
    _S('040102', 'Biomedicina.', None),
    _S('040201', 'Análises clínicas e congêneres.', None),
    _S('040202', 'Patologia e congêneres.', None),
    _S('040203', 'Eletricidade médica (eletroestimulação de nervos e musculos, cardioversão, etc) e congêneres.', None),
    _S('040204', 'Radioterapia, quimioterapia e congêneres.', None),
    _S('040205', 'Ultra-sonografia, ressonância magnética, radiologia, tomografia e congêneres.', None),
    _S('040301', 'Hospitais e congêneres.', None),
    _S('040302', 'Laboratórios e congêneres.', None),
    _S('040303', 'Clínicas, sanatórios, manicômios, casas de saúde, prontos-socorros, ambulatórios e congêneres.', None),
    _S('040401', 'Instrumentação cirúrgica.', None),
    _S('040501', 'Acupuntura.', None),
    _S('040601', 'Enfermagem, inclusive serviços auxiliares.', None),
    _S('040701', 'Serviços farmacêuticos.', None),
    _S('040801', 'Terapia ocupacional.', None),
    _S('040802', 'Fisioterapia.', None),
    _S('040803', 'Fonoaudiologia.', None),
    _S('040901', 'Terapias de qualquer espécie destinadas ao tratamento físico, orgânico e mental.', None),
    _S('041001', 'Nutrição.', None),
    _S('041101', 'Obstetrícia.', None),
    _S('041201', 'Odontologia.', None),
    _S('041301', 'Ortóptica.', None),
    _S('041401', 'Próteses sob encomenda.', None),
    _S('041501', 'Psicanálise.', None),
    _S('041601', 'Psicologia.', None),
    _S('041701', 'Casas de repouso e congêneres.', None),
    _S('041702', 'Casas de recuperação e congêneres.', None),
    _S('041703', 'Creches e congêneres.', None),
    _S('041704', 'Asilos e congêneres.', None),
    _S('041801', 'Inseminação artificial, fertilização in vitro e congêneres.', None),
    _S('041901', 'Bancos de sangue, leite, pele, olhos, óvulos, sêmen e congêneres.', None),
    _S('042001', 'Coleta de sangue, leite, tecidos, sêmen, órgãos e materiais biológicos de qualquer espécie.', None),
    _S('042101', 'Unidade de atendimento, assistência ou tratamento móvel e congêneres.', None),
    _S('042201', 'Planos de medicina de grupo ou individual e convênios para prestação de assistência médica, hospitalar, odontológica e congêneres.', None),
    _S('042301', 'Outros planos de saúde que se cumpram através de serviços de terceiros contratados, credenciados, cooperados ou apenas pagos pelo operador do plano mediante indicação do beneficiário.', None),
    _S('050101', 'Medicina veterinária', None),
    _S('050102', 'Zootecnia.', None),
    _S('050201', 'Hospitais e congêneres, na área veterinária.', None),
    _S('050202', 'Clínicas, ambulatórios, prontos-socorros e congêneres, na área veterinária.', None),
    _S('050301', 'Laboratórios de análise na área veterinária.', None),
    _S('050401', 'Inseminação artificial, fertilização in vitro e congêneres.', None),
    _S('050501', 'Bancos de sangue e de órgãos e congêneres.', None),
    _S('050601', 'Coleta de sangue, leite, tecidos, sêmen, órgãos e materiais biológicos de qualquer espécie.', None),
    _S('050701', 'Unidade de atendimento, assistência ou tratamento móvel e congêneres.', None),
    _S('050801', 'Guarda, tratamento, amestramento, embelezamento, alojamento e congêneres.', None),
    _S('050901', 'Planos de atendimento e assistência médico-veterinária.', None),
    _S('060101', 'Barbearia, cabeleireiros, manicuros, pedicuros e congêneres.', None),
    _S('060201', 'Esteticistas, tratamento de pele, depilação e congêneres.', None),
    _S('060301', 'Banhos, duchas, sauna, massagens e congêneres.', None),
    _S('060401', 'Ginástica, dança, esportes, natação, artes marciais e demais atividades físicas.', None),
    _S('060501', 'Centros de emagrecimento, spa e congêneres.', None),
    _S('060601', 'Aplicação de tatuagens, piercings e congêneres.', None),
    _S('070101', 'Engenharia e congêneres.', None),
    _S('070102', 'Agronomia e congêneres.', None),
    _S('070103', 'Agrimensura e congêneres.', None),
    _S('070104', 'Arquitetura, urbanismo e congêneres.', None),
    _S('070105', 'Geologia e congêneres.', None),
    _S('070106', 'Paisagismo e congêneres.', None),
    _S('070201', 'Execução, por administração, de obras de construção civil, hidráulica ou elétrica e de outras obras semelhantes, inclusive sondagem, perfuração de poços, escavação, drenagem e irrigação, terraplanagem, pavimentação, concretagem e a instalação e montagem de produtos, peças e equipamentos (exceto o fornecimento de mercadorias produzidas pelo prestador de serviços fora do local da prestação dos serviços, que fica sujeito ao ICMS).', 'obra'),
    _S('070202', 'Execução, por empreitada ou subempreitada, de obras de construção civil, hidráulica ou elétrica e de outras obras semelhantes, inclusive sondagem, perfuração de poços, escavação, drenagem e irrigação, terraplanagem, pavimentação, concretagem e a instalação e montagem de produtos, peças e equipamentos (exceto o fornecimento de mercadorias produzidas pelo prestador de serviços fora do local da prestação dos serviços, que fica sujeito ao ICMS).', 'obra'),
    _S('070301', 'Elaboração de planos diretores, estudos de viabilidade, estudos organizacionais e outros, relacionados com obras e serviços de engenharia.', None),
    _S('070302', 'Elaboração de anteprojetos, projetos básicos e projetos executivos para trabalhos de engenharia.', None),
    _S('070401', 'Demolição.', 'obra'),
    _S('070501', 'Reparação, conservação e reforma de edifícios e congêneres (exceto o fornecimento de mercadorias produzidas pelo prestador dos serviços, fora do local da prestação dos serviços, que fica sujeito ao ICMS).', 'obra'),
    _S('070502', 'Reparação, conservação e reforma de estradas, pontes, portos e congêneres (exceto o fornecimento de mercadorias produzidas pelo prestador dos serviços, fora do local da prestação dos serviços, que fica sujeito ao ICMS).', 'obra'),
    _S('070601', 'Colocação e instalação de tapetes, carpetes, cortinas e congêneres, com material fornecido pelo tomador do serviço.', 'obra'),
    _S('070602', 'Colocação e instalação de assoalhos, revestimentos de parede, vidros, divisórias, placas de gesso e congêneres, com material fornecido pelo tomador do serviço.', 'obra'),
    _S('070701', 'Recuperação, raspagem, polimento e lustração de pisos e congêneres.', 'obra'),
    _S('070801', 'Calafetação.', 'obra'),
    _S('070901', 'Varrição, coleta e remoção de lixo, rejeitos e outros resíduos quaisquer.', None),
    _S('070902', 'Incineração, tratamento, reciclagem, separação e destinação final de lixo, rejeitos e outros resíduos quaisquer.', None),
    _S('071001', 'Limpeza, manutenção e conservação de vias e logradouros públicos, parques, jardins e congêneres.', None),
    _S('071002', 'Limpeza, manutenção e conservação de imóveis, chaminés, piscinas e congêneres.', None),
    _S('071101', 'Decoração.', None),
    _S('071102', 'Jardinagem, inclusive corte e poda de árvores.', None),
    _S('071201', 'Controle e tratamento de efluentes de qualquer natureza e de agentes físicos, químicos e biológicos.', None),
    _S('071301', 'Dedetização, desinfecção, desinsetização, imunização, higienização, desratização, pulverização e congêneres.', None),
    _S('071601', 'Florestamento, reflorestamento, semeadura, adubação, reparação de solo, plantio, silagem, colheita, corte e descascamento de árvores, silvicultura, exploração florestal e dos serviços congêneres indissociáveis da formação, manutenção e colheita de florestas, para quaisquer fins e por quaisquer meios.', None),
    _S('071701', 'Escoramento, contenção de encostas e serviços congêneres.', 'obra'),
    _S('071801', 'Limpeza e dragagem de rios, portos, canais, baías, lagos, lagoas, represas, açudes e congêneres.', None),
    _S('071901', 'Acompanhamento e fiscalização da execução de obras de engenharia, arquitetura e urbanismo.', 'obra'),
    _S('072001', 'Aerofotogrametria (inclusive interpretação), cartografia, mapeamento e congêneres.', None),
    _S('072002', 'Levantamentos batimétricos, geográficos, geodésicos, geológicos, geofísicos e congêneres.', None),
    _S('072003', 'Levantamentos topográficos e congêneres.', None),
    _S('072101', 'Pesquisa, perfuração, cimentação, mergulho, perfilagem, concretação, testemunhagem, pescaria, estimulação e outros serviços relacionados com a exploração e explotação de petróleo, gás natural e de outros recursos minerais.', None),
    _S('072201', 'Nucleação e bombardeamento de nuvens e congêneres.', None),
    _S('080101', 'Ensino regular pré-escolar, fundamental e médio.', None),
    _S('080102', 'Ensino regular superior.', None),
    _S('080201', 'Instrução, treinamento, orientação pedagógica e educacional, avaliação de conhecimentos de qualquer natureza.', None),
    _S('090101', 'Hospedagem em hotéis, hotelaria marítima e congêneres (o valor da alimentação e gorjeta, quando incluído no preço da diária, fica sujeito ao Imposto Sobre Serviços).', None),
    _S('090102', 'Hospedagem em pensões, albergues, pousadas, hospedarias, ocupação por temporada com fornecimento de serviços e congêneres (o valor da alimentação e gorjeta, quando incluído no preço da diária, fica sujeito ao Imposto Sobre Serviços).', None),
    _S('090103', 'Hospedagem em motéis e congêneres (o valor da alimentação e gorjeta, quando incluído no preço da diária, fica sujeito ao Imposto Sobre Serviços).', None),
    _S('090104', 'Hospedagem em apart-service condominiais, flat, apart-hotéis, hotéis residência, residence-service, suite service e congêneres (o valor da alimentação e gorjeta, quando incluído no preço da diária, fica sujeito ao Imposto Sobre Serviços).', None),
    _S('090201', 'Agenciamento e intermediação de programas de turismo, passeios, viagens, excursões, hospedagens e congêneres.', None),
    _S('090202', 'Organização, promoção e execução de programas de turismo, passeios, viagens, excursões, hospedagens e congêneres.', None),
    _S('090301', 'Guias de turismo.', None),
    _S('100101', 'Agenciamento, corretagem ou intermediação de câmbio.', None),
    _S('100102', 'Agenciamento, corretagem ou intermediação de seguros.', None),
    _S('100103', 'Agenciamento, corretagem ou intermediação de cartões de crédito.', None),
    _S('100104', 'Agenciamento, corretagem ou intermediação de planos de saúde.', None),
    _S('100105', 'Agenciamento, corretagem ou intermediação de planos de previdência privada.', None),
    _S('100201', 'Agenciamento, corretagem ou intermediação de títulos em geral e valores mobiliários.', None),
    _S('100202', 'Agenciamento, corretagem ou intermediação de contratos quaisquer.', None),
    _S('100301', 'Agenciamento, corretagem ou intermediação de direitos de propriedade industrial, artística ou literária.', None),
    _S('100401', 'Agenciamento, corretagem ou intermediação de contratos de arrendamento mercantil (leasing).', None),
    _S('100402', 'Agenciamento, corretagem ou intermediação de contratos de franquia (franchising).', None),
    _S('100403', 'Agenciamento, corretagem ou intermediação de faturização (factoring).', None),
    _S('100501', 'Agenciamento, corretagem ou intermediação de bens móveis ou imóveis, não abrangidos em outros itens ou subitens, por quaisquer meios.', None),
    _S('100502', 'Agenciamento, corretagem ou intermediação de bens móveis ou imóveis realizados no âmbito de Bolsas de Mercadorias e Futuros, por quaisquer meios.', None),
    _S('100601', 'Agenciamento marítimo.', None),
    _S('100701', 'Agenciamento de notícias.', None),
    _S('100801', 'Agenciamento de publicidade e propaganda, inclusive o agenciamento de veiculação por quaisquer meios.', None),
    _S('100901', 'Representação de qualquer natureza, inclusive comercial.', None),
    _S('101001', 'Distribuição de bens de terceiros.', None),
    _S('110101', 'Guarda e estacionamento de veículos terrestres automotores.', None),
    _S('110102', 'Guarda e estacionamento de aeronaves e de embarcações.', None),
    _S('110201', 'Vigilância, segurança ou monitoramento de bens, pessoas e semoventes.', None),
    _S('110301', 'Escolta, inclusive de veículos e cargas.', None),
    _S('110401', 'Armazenamento, depósito, guarda de bens de qualquer espécie.', None),
    _S('110402', 'Carga, descarga, arrumação de bens de qualquer espécie.', None),
    _S('110501', 'Serviços relacionados ao monitoramento e rastreamento a distância, em qualquer via ou local, de veículos, cargas, pessoas e semoventes em circulação ou movimento, realizados por meio de telefonia móvel, transmissão de satélites, rádio ou qualquer outro meio, inclusive pelas empresas de Tecnologia da Informação Veicular, independentemente de o prestador de serviços ser proprietário ou não da infraestrutura de telecomunicações que utiliza.', None),
    _S('120101', 'Espetáculos teatrais.', 'atvEvento'),
    _S('120201', 'Exibições cinematográficas.', 'atvEvento'),
    _S('120301', 'Espetáculos circenses.', 'atvEvento'),
    _S('120401', 'Programas de auditório.', 'atvEvento'),
    _S('120501', 'Parques de diversões, centros de lazer e congêneres.', 'atvEvento'),
    _S('120601', 'Boates, taxi-dancing e congêneres.', 'atvEvento'),
    _S('120701', 'Shows, ballet, danças, desfiles, bailes, óperas, concertos, recitais, festivais e congêneres.', 'atvEvento'),
    _S('120801', 'Feiras, exposições, congressos e congêneres.', 'atvEvento'),
    _S('120901', 'Bilhares.', 'atvEvento'),
    _S('120902', 'Boliches.', 'atvEvento'),
    _S('120903', 'Diversões eletrônicas ou não.', 'atvEvento'),
    _S('121001', 'Corridas e competições de animais.', 'atvEvento'),
    _S('121101', 'Competições esportivas ou de destreza física ou intelectual, com ou sem a participação do espectador.', 'atvEvento'),
    _S('121201', 'Execução de música.', 'atvEvento'),
    _S('121301', 'Produção, mediante ou sem encomenda prévia, de eventos, espetáculos, entrevistas, shows, ballet, danças, desfiles, bailes, teatros, óperas, concertos, recitais, festivais e congêneres.', 'atvEvento'),
    _S('121401', 'Fornecimento de música para ambientes fechados ou não, mediante transmissão por qualquer processo.', 'atvEvento'),
    _S('121501', 'Desfiles de blocos carnavalescos ou folclóricos, trios elétricos e congêneres.', 'atvEvento'),
    _S('121601', 'Exibição de filmes, entrevistas, musicais, espetáculos, shows, concertos, desfiles, óperas, competições esportivas, de destreza intelectual ou congêneres.', 'atvEvento'),
    _S('121701', 'Recreação e animação, inclusive em festas e eventos de qualquer natureza.', 'atvEvento'),
    _S('130201', 'Fonografia ou gravação de sons, inclusive trucagem, dublagem, mixagem e congêneres.', None),
    _S('130301', 'Fotografia e cinematografia, inclusive revelação, ampliação, cópia, reprodução, trucagem e congêneres.', None),
    _S('130401', 'Reprografia, microfilmagem e digitalização.', None),
    _S('130501', 'Composição gráfica, inclusive confecção de impressos gráficos, fotocomposição, clicheria, zincografia, litografia e fotolitografia, exceto se destinados a posterior operação de comercialização ou industrialização, ainda que incorporados, de qualquer forma, a outra mercadoria que deva ser objeto de posterior circulação, tais como bulas, rótulos, etiquetas, caixas, cartuchos, embalagens e manuais técnicos e de instrução, quando ficarão sujeitos ao ICMS.', None),
    _S('140101', 'Lubrificação, limpeza, lustração, revisão, carga e recarga, conserto, restauração, blindagem, manutenção e conservação de máquinas, veículos, aparelhos, equipamentos, motores, elevadores ou de qualquer objeto (exceto peças e partes empregadas, que ficam sujeitas ao ICMS).', None),
    _S('140201', 'Assistência técnica.', None),
    _S('140301', 'Recondicionamento de motores (exceto peças e partes empregadas, que ficam sujeitas ao ICMS).', None),
    _S('140401', 'Recauchutagem ou regeneração de pneus.', None),
    _S('140501', 'Restauração, recondicionamento, acondicionamento, pintura, beneficiamento, lavagem, secagem, tingimento, galvanoplastia, anodização, corte, recorte, plastificação, costura, acabamento, polimento e congêneres de objetos quaisquer.', None),
    _S('140601', 'Instalação e montagem de aparelhos, máquinas e equipamentos, inclusive montagem industrial, prestados ao usuário final, exclusivamente com material por ele fornecido.', None),
    _S('140701', 'Colocação de molduras e congêneres.', None),
    _S('140801', 'Encadernação, gravação e douração de livros, revistas e congêneres.', None),
    _S('140901', 'Alfaiataria e costura, quando o material for fornecido pelo usuário final, exceto aviamento.', None),
    _S('141001', 'Tinturaria e lavanderia.', None),
    _S('141101', 'Tapeçaria e reforma de estofamentos em geral.', None),
    _S('141201', 'Funilaria e lanternagem.', None),
    _S('141301', 'Carpintaria.', None),
    _S('141302', 'Serralheria.', None),
    _S('141401', 'Guincho intramunicipal.', None),
    _S('141402', 'Guindaste e içamento.', None),
    _S('141403', 'Guincho intramunicipal em construção civil.', 'obra'),
    _S('141404', 'Guindaste e içamento em construção civil.', 'obra'),
    _S('150101', 'Administração de fundos quaisquer e congêneres.', None),
    _S('150102', 'Administração de consórcio e congêneres.', None),
    _S('150103', 'Administração de cartão de crédito ou débito e congêneres.', None),
    _S('150104', 'Administração de carteira de clientes e congêneres.', None),
    _S('150105', 'Administração de cheques pré-datados e congêneres.', None),
    _S('150201', 'Abertura de conta-corrente no País, bem como a manutenção da referida conta ativa e inativa.', None),
    _S('150202', 'Abertura de conta-corrente no exterior, bem como a manutenção da referida conta ativa e inativa.', None),
    _S('150203', 'Abertura de conta de investimentos e aplicação no País, bem como a manutenção da referida conta ativa e inativa.', None),
    _S('150204', 'Abertura de conta de investimentos e aplicação no exterior, bem como a manutenção da referida conta ativa e inativa.', None),
    _S('150205', 'Abertura de caderneta de poupança no País, bem como a manutenção da referida conta ativa e inativa.', None),
    _S('150206', 'Abertura de caderneta de poupança no exterior, bem como a manutenção da referida conta ativa e inativa.', None),
    _S('150207', 'Abertura de contas em geral no País, não abrangida em outro subitem, bem como a manutenção das referidas contas ativas e inativas.', None),
    _S('150208', 'Abertura de contas em geral no exterior, não abrangida em outro subitem, bem como a manutenção das referidas contas ativas e inativas.', None),
    _S('150301', 'Locação de cofres particulares.', None),
    _S('150302', 'Manutenção de cofres particulares.', None),
    _S('150303', 'Locação de terminais eletrônicos.', None),
    _S('150304', 'Manutenção de terminais eletrônicos.', None),
    _S('150305', 'Locação de terminais de atendimento.', None),
    _S('150306', 'Manutenção de terminais de atendimento.', None),
    _S('150307', 'Locação de bens e equipamentos em geral.', None),
    _S('150308', 'Manutenção de bens e equipamentos em geral.', None),
    _S('150401', 'Fornecimento ou emissão de atestados em geral, inclusive atestado de idoneidade, atestado de capacidade financeira e congêneres.', None),
    _S('150501', 'Cadastro, elaboração de ficha cadastral, renovação cadastral e congêneres.', None),
    _S('150502', 'Inclusão no Cadastro de Emitentes de Cheques sem Fundos - CCF.', None),
    _S('150503', 'Exclusão no Cadastro de Emitentes de Cheques sem Fundos - CCF.', None),
    _S('150504', 'Inclusão em quaisquer outros bancos cadastrais.', None),
    _S('150505', 'Exclusão em quaisquer outros bancos cadastrais.', None),
    _S('150601', 'Emissão, reemissão e fornecimento de avisos, comprovantes e documentos em geral', None),
    _S('150602', 'Abono de firmas.', None),
    _S('150603', 'Coleta e entrega de documentos, bens e valores.', None),
    _S('150604', 'Comunicação com outra agência ou com a administração central.', None),
    _S('150605', 'Licenciamento eletrônico de veículos.', None),
    _S('150606', 'Transferência de veículos.', None),
    _S('150607', 'Agenciamento fiduciário ou depositário.', None),
    _S('150608', 'Devolução de bens em custódia.', None),
    _S('150701', 'Acesso, movimentação, atendimento e consulta a contas em geral, por qualquer meio ou processo, inclusive por telefone, fac-símile, internet e telex.', None),
    _S('150702', 'Acesso a terminais de atendimento, inclusive vinte e quatro horas.', None),
    _S('150703', 'Acesso a outro banco e à rede compartilhada.', None),
    _S('150704', 'Fornecimento de saldo, extrato e demais informações relativas a contas em geral, por qualquer meio ou processo.', None),
    _S('150801', 'Emissão, reemissão, alteração, cessão, substituição, cancelamento e registro de contrato de crédito.', None),
    _S('150802', 'Estudo, análise e avaliação de operações de crédito.', None),
    _S('150803', 'Emissão, concessão, alteração ou contratação de aval, fiança, anuência e congêneres.', None),
    _S('150804', 'Serviços relativos à abertura de crédito, para quaisquer fins.', None),
    _S('150901', 'Arrendamento mercantil (leasing) de quaisquer bens, inclusive cessão de direitos e obrigações, substituição de garantia, alteração, cancelamento e registro de contrato, e demais serviços relacionados ao arrendamento mercantil (leasing).', None),
    _S('151001', 'Serviços relacionados a cobranças em geral, de títulos quaisquer, de contas ou carnês, de câmbio, de tributos e por conta de terceiros, inclusive os efetuados por meio eletrônico, automático ou por máquinas de atendimento.', None),
    _S('151002', 'Serviços relacionados a recebimentos em geral, de títulos quaisquer, de contas ou carnês, de câmbio, de tributos e por conta de terceiros, inclusive os efetuados por meio eletrônico, automático ou por máquinas de atendimento.', None),
    _S('151003', 'Serviços relacionados a pagamentos em geral, de títulos quaisquer, de contas ou carnês, de câmbio, de tributos e por conta de terceiros, inclusive os efetuados por meio eletrônico, automático ou por máquinas de atendimento.', None),
    _S('151004', 'Serviços relacionados a fornecimento de posição de cobrança, recebimento ou pagamento.', None),
    _S('151005', 'Serviços relacionados a emissão de carnês, fichas de compensação, impressos e documentos em geral.', None),
    _S('151101', 'Devolução de títulos, protesto de títulos, sustação de protesto, manutenção de títulos, reapresentação de títulos, e demais serviços a eles relacionados.', None),
    _S('151201', 'Custódia em geral, inclusive de títulos e valores mobiliários.', None),
    _S('151301', 'Serviços relacionados a operações de câmbio em geral, edição, alteração, prorrogação, cancelamento e baixa de contrato de câmbio.', None),
    _S('151302', 'Serviços relacionados a emissão de registro de exportação ou de crédito.', None),
    _S('151303', 'Serviços relacionados a cobrança ou depósito no exterior.', None),
    _S('151304', 'Serviços relacionados a emissão, fornecimento e cancelamento de cheques de viagem.', None),
    _S('151305', 'Serviços relacionados a fornecimento, transferência, cancelamento e demais serviços relativos a carta de crédito de importação, exportação e garantias recebidas.', None),
    _S('151306', 'Serviços relacionados a envio e recebimento de mensagens em geral relacionadas a operações de câmbio.', None),
    _S('151401', 'Fornecimento, emissão, reemissão de cartão magnético, cartão de crédito, cartão de débito, cartão salário e congêneres.', None),
    _S('151402', 'Renovação de cartão magnético, cartão de crédito, cartão de débito, cartão salário e congêneres.', None),
    _S('151403', 'Manutenção de cartão magnético, cartão de crédito, cartão de débito, cartão salário e congêneres.', None),
    _S('151501', 'Compensação de cheques e títulos quaisquer.', None),
    _S('151502', 'Serviços relacionados a depósito, inclusive depósito identificado, a saque de contas quaisquer, por qualquer meio ou processo, inclusive em terminais eletrônicos e de atendimento.', None),
    _S('151601', 'Emissão, reemissão, liquidação, alteração, cancelamento e baixa de ordens de pagamento, ordens de crédito e similares, por qualquer meio ou processo.', None),
    _S('151602', 'Serviços relacionados à transferência de valores, dados, fundos, pagamentos e similares, inclusive entre contas em geral.', None),
    _S('151701', 'Emissão e fornecimento de cheques quaisquer, avulso ou por talão.', None),
    _S('151702', 'Devolução de cheques quaisquer, avulso ou por talão.', None),
    _S('151703', 'Sustação, cancelamento e oposição de cheques quaisquer, avulso ou por talão.', None),
    _S('151801', 'Serviços relacionados a crédito imobiliário, de avaliação e vistoria de imóvel ou obra.', None),
    _S('151802', 'Serviços relacionados a crédito imobiliário, de análise técnica e jurídica.', None),
    _S('151803', 'Serviços relacionados a crédito imobiliário, de emissão, reemissão, alteração, transferência e renegociação de contrato.', None),
    _S('151804', 'Serviços relacionados a crédito imobiliário, de emissão e reemissão do termo de quitação.', None),
    _S('151805', 'Demais serviços relacionados a crédito imobiliário.', None),
    _S('160101', 'Serviços de transporte coletivo municipal rodoviário de passageiros.', None),
    _S('160102', 'Serviços de transporte coletivo municipal metroviário de passageiros.', None),
    _S('160103', 'Serviços de transporte coletivo municipal ferroviário de passageiros.', None),
    _S('160104', 'Serviços de transporte coletivo municipal aquaviário de passageiros.', None),
    _S('160201', 'Outros serviços de transporte de natureza municipal.', None),
    _S('170101', 'Assessoria ou consultoria de qualquer natureza, não contida em outros itens desta lista.', None),
    _S('170102', 'Análise, exame, pesquisa, coleta, compilação e fornecimento de dados e informações de qualquer natureza, inclusive cadastro e similares.', None),
    _S('170201', 'Datilografia, digitação, estenografia e congêneres.', None),
    _S('170202', 'Expediente, secretaria em geral, apoio e infra-estrutura administrativa e congêneres.', None),
    _S('170203', 'Resposta audível e congêneres.', None),
    _S('170204', 'Redação, edição, revisão e congêneres.', None),
    _S('170205', 'Interpretação, tradução e congêneres.', None),
    _S('170301', 'Planejamento, coordenação, programação ou organização técnica.', None),
    _S('170302', 'Planejamento, coordenação, programação ou organização financeira.', None),
    _S('170303', 'Planejamento, coordenação, programação ou organização administrativa.', None),
    _S('170401', 'Recrutamento, agenciamento, seleção e colocação de mão-de-obra.', None),
    _S('170501', 'Fornecimento de mão-de-obra, mesmo em caráter temporário, inclusive de empregados ou trabalhadores, avulsos ou temporários, contratados pelo prestador de serviço.', None),
    _S('170601', 'Propaganda e publicidade, inclusive promoção de vendas, planejamento de campanhas ou sistemas de publicidade, elaboração de desenhos, textos e demais materiais publicitários.', None),
    _S('170801', 'Franquia (franchising).', None),
    _S('170901', 'Perícias, laudos, exames técnicos e análises técnicas.', None),
    _S('171001', 'Planejamento, organização e administração de feiras, exposições, e congêneres.', None),
    _S('171002', 'Planejamento, organização e administração de congressos e congêneres.', None),
    _S('171101', 'Organização de festas e recepções.', None),
    _S('171102', 'Bufê (exceto o fornecimento de alimentação e bebidas, que fica sujeito ao ICMS).', None),
    _S('171201', 'Administração em geral, inclusive de bens e negócios de terceiros.', None),
    _S('171301', 'Leilão e congêneres.', None),
    _S('171401', 'Advocacia', None),
    _S('171501', 'Arbitragem de qualquer espécie, inclusive jurídica.', None),
    _S('171601', 'Auditoria.', None),
    _S('171701', 'Análise de Organização e Métodos.', None),
    _S('171801', 'Atuária e cálculos técnicos de qualquer natureza.', None),
    _S('171901', 'Contabilidade, inclusive serviços técnicos e auxiliares.', None),
    _S('172001', 'Consultoria e assessoria econômica ou financeira.', None),
    _S('172101', 'Estatística.', None),
    _S('172201', 'Cobrança em geral.', None),
    _S('172301', 'Assessoria, análise, avaliação, atendimento, consulta, cadastro, seleção, gerenciamento de informações, administração de contas a receber ou a pagar e em geral, relacionados a operações de faturização (factoring).', None),
    _S('172401', 'Apresentação de palestras, conferências, seminários e congêneres.', None),
    _S('172501', 'Inserção de textos, desenhos e outros materiais de propaganda e publicidade, em qualquer meio (exceto em livros, jornais, periódicos e nas modalidades de serviços de radiodifusão sonora e de sons e imagens de recepção livre e gratuita).', None),
    _S('180101', 'Serviços de regulação de sinistros vinculados a contratos de seguros e congêneres.', None),
    _S('180102', 'Serviços de inspeção e avaliação de riscos para cobertura de contratos de seguros e congêneres.', None),
    _S('180103', 'Serviços de prevenção e gerência de riscos seguráveis e congêneres.', None),
    _S('190101', 'Serviços de distribuição e venda de bilhetes e demais produtos de loteria, cartões, pules ou cupons de apostas, sorteios, prêmios, inclusive os decorrentes de títulos de capitalização e congêneres.', None),
    _S('190102', 'Serviços de distribuição e venda de bingos e congêneres.', None),
    _S('200101', 'Serviços portuários, ferroportuários, utilização de porto, movimentação de passageiros, reboque de embarcações, rebocador escoteiro, atracação, desatracação, serviços de praticagem, capatazia, armazenagem de qualquer natureza, serviços acessórios, movimentação de mercadorias, serviços de apoio marítimo, de movimentação ao largo, serviços de armadores, estiva, conferência, logística e congêneres.', None),
    _S('200201', 'Serviços aeroportuários, utilização de aeroporto, movimentação de passageiros, armazenagem de qualquer natureza, capatazia, movimentação de aeronaves, serviços de apoio aeroportuários, serviços acessórios, movimentação de mercadorias, logística e congêneres.', None),
    _S('200301', 'Serviços de terminais rodoviários, ferroviários, metroviários, movimentação de passageiros, mercadorias, inclusive suas operações, logística e congêneres.', None),
    _S('210101', 'Serviços de registros públicos, cartorários e notariais.', None),
    _S('220101', 'Serviços de exploração de rodovia mediante cobrança de preço ou pedágio dos usuários, envolvendo execução de serviços de conservação, manutenção, melhoramentos para adequação de capacidade e segurança de trânsito, operação, monitoração, assistência aos usuários e outros serviços definidos em contratos, atos de concessão ou de permissão ou em normas oficiais.', None),
    _S('230101', 'Serviços de programação e comunicação visual e congêneres.', None),
    _S('230102', 'Serviços de desenho industrial e congêneres.', None),
    _S('240101', 'Serviços de chaveiros, confecção de carimbos e congêneres.', None),
    _S('240102', 'Serviços de placas, sinalização visual, banners, adesivos e congêneres.', None),
    _S('250101', 'Funerais, inclusive fornecimento de caixão, urna ou esquifes; aluguel de capela; transporte do corpo cadavérico; fornecimento de flores, coroas e outros paramentos; desembaraço de certidão de óbito; fornecimento de véu, essa e outros adornos; embalsamento, embelezamento, conservação ou restauração de cadáveres.', None),
    _S('250201', 'Translado intramunicipal de corpos e partes de corpos cadavéricos.', None),
    _S('250202', 'Cremação de corpos e partes de corpos cadavéricos.', None),
    _S('250301', 'Planos ou convênio funerários.', None),
    _S('250401', 'Manutenção e conservação de jazigos e cemitérios.', None),
    _S('250501', 'Cessão de uso de espaços em cemitérios para sepultamento.', None),
    _S('260101', 'Serviços de coleta, remessa ou entrega de correspondências, documentos, objetos, bens ou valores, inclusive pelos correios e suas agências franqueadas.', None),
    _S('260102', 'Serviços de courrier e congêneres.', None),
    _S('270101', 'Serviços de assistência social.', None),
    _S('280101', 'Serviços de avaliação de bens e serviços de qualquer natureza.', None),
    _S('290101', 'Serviços de biblioteconomia.', None),
    _S('300101', 'Serviços de biologia e biotecnologia.', None),
    _S('300102', 'Serviços de química.', None),
    _S('310101', 'Serviços técnicos em edificações e congêneres.', None),
    _S('310102', 'Serviços técnicos em eletrônica, eletrotécnica e congêneres.', None),
    _S('310103', 'Serviços técnicos em mecânica e congêneres.', None),
    _S('310104', 'Serviços técnicos em telecomunicações e congêneres.', None),
    _S('320101', 'Serviços de desenhos técnicos.', None),
    _S('330101', 'Serviços de desembaraço aduaneiro, comissários, despachantes e congêneres.', None),
    _S('340101', 'Serviços de investigações particulares, detetives e congêneres.', None),
    _S('350101', 'Serviços de reportagem e jornalismo.', None),
    _S('350102', 'Serviços de assessoria de imprensa.', None),
    _S('350103', 'Serviços de relações públicas.', None),
    _S('360101', 'Serviços de meteorologia.', None),
    _S('370101', 'Serviços de artistas, atletas, modelos e manequins.', None),
    _S('380101', 'Serviços de museologia.', None),
    _S('390101', 'Serviços de ourivesaria e lapidação (quando o material for fornecido pelo tomador do serviço).', None),
    _S('400101', 'Obras de arte sob encomenda.', None),
    _S('990101', 'Serviços sem a incidência de ISSQN e ICMS', None),
)

TOTAL_DE_SERVICOS = len(SERVICOS)

# Asserção de build, não de teste. Roda no import: um catálogo gerado torto derruba
# a biblioteca na hora em vez de deixar um `cTribNac` de 5 dígitos chegar à SEFIN e
# voltar rejeitado.
assert (
    TOTAL_DE_SERVICOS == 337
), f"catálogo com {TOTAL_DE_SERVICOS} entradas, esperado 337"
assert all(re.fullmatch(r"[0-9]{6}", s.codigo) for s in SERVICOS), "código fora de [0-9]{6}"
assert len({s.codigo for s in SERVICOS}) == TOTAL_DE_SERVICOS, "código duplicado no catálogo"

_POR_CODIGO: dict[str, Servico] = {s.codigo: s for s in SERVICOS}


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento, espaços colapsados — para busca tolerante."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


_BUSCAVEL: tuple[tuple[str, Servico], ...] = tuple(
    (_normalizar(s.descricao), s) for s in SERVICOS
)


def por_codigo(codigo: str) -> Servico | None:
    """Busca exata por `cTribNac`.

    Aceita as três notações que o anexo usa para a mesma coisa: `010101`, `10101`
    (sem o zero à esquerda, como saiu do Excel) e `01.01.01` (texto corrido).
    """
    limpo = re.sub(r"\D", "", codigo)
    if not limpo:
        return None
    return _POR_CODIGO.get(limpo.zfill(6))


# Palavras curtas demais ou vazias de sentido para pesar numa busca. Sem isto,
# "banho e tosa" casaria com toda descrição que contenha "e".
_IRRELEVANTES = frozenset(
    {"de", "da", "do", "das", "dos", "e", "ou", "em", "no", "na", "com", "por", "para"}
)


def _termos(texto: str) -> list[str]:
    return [p for p in _normalizar(texto).split() if len(p) >= 3 and p not in _IRRELEVANTES]


def buscar_servico(texto: str) -> tuple[Servico, ...]:
    """Procura serviços por descrição, ignorando acento e caixa.

    Existe para o dev que sabe que vende "banho e tosa" e não faz ideia de que a
    lista nacional chama isso de `060301`. Um texto que pareça código cai na busca
    exata por `cTribNac`.

    A procura tem três degraus, do mais específico ao mais tolerante, e para no
    primeiro que devolver alguma coisa:

    1. a frase inteira como substring da descrição;
    2. descrições que contenham **todos** os termos, em qualquer ordem;
    3. descrições que contenham **algum** termo, ordenadas por quantos casaram.

    O degrau 3 é o que faz "banho e tosa" encontrar `060301`: a lista nacional não
    tem a palavra "tosa" em lugar nenhum, e uma busca só por substring devolveria
    vazio para a consulta mais óbvia que este catálogo deveria atender.
    """
    if not texto or not texto.strip():
        return ()

    exato = por_codigo(texto) if re.fullmatch(r"[\d.]+", texto.strip()) else None
    if exato is not None:
        return (exato,)

    alvo = _normalizar(texto)
    frase = tuple(servico for descricao, servico in _BUSCAVEL if alvo in descricao)
    if frase:
        return frase

    termos = _termos(texto)
    if not termos:
        return ()

    todos = tuple(
        servico
        for descricao, servico in _BUSCAVEL
        if all(termo in descricao for termo in termos)
    )
    if todos:
        return todos

    algum = [
        (sum(termo in descricao for termo in termos), servico)
        for descricao, servico in _BUSCAVEL
        if any(termo in descricao for termo in termos)
    ]
    algum.sort(key=lambda par: (-par[0], par[1].codigo))
    return tuple(servico for _, servico in algum)
