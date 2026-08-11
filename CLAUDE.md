# nfse_nacional

Biblioteca Python (MIT) para integração com a API REST do Sistema Nacional NFS-e
(SEFIN Nacional / gov.br/nfse).

## Documentos de referência (fonte da verdade, não inventar leiaute)

- `manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e-v1-2-out2025.md` — 4 grupos de endpoints REST
- `anexo_i-sefin_adn-dps_nfse-snnfse-v1-01-20260209.md` — lista de serviços, cenários de exportação, `RN_RECEPCAO_DPS`, `LEIAUTE DPS_NFS-e`, `RN DPS_NFS-e`
- `anexo_ii-sefin_adn-pedregevt_evt-snnfse-v1-01-20260122.md` — tipos de evento, `RN EVENTOSxEVENTOS`, leiaute do PedRegEvt
- `prompt-claude-code-nfse-nacional.md` — plano de implementação em 8 fases

Arquivos `:Zone.Identifier` são metadados do Windows, ignorar.

A linha `#Ref` na coluna de numeração de `RN DPS_NFS-e` é fórmula Excel quebrada
no documento original do governo, não erro de conversão.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
