<!--
O DESIGN.md é a fonte da verdade deste projeto. Decisão travada lá não se
re-litiga sem evidência nova — e se este PR traz essa evidência, ela vai na
seção "Decisões" abaixo, não na descrição solta.
-->

## O que muda

<!-- Uma frase. O que passa a ser possível depois deste PR que não era antes. -->

## Por quê

<!--
O problema, não a solução. Se o PR fecha uma OQ do DESIGN.md ou um item de
"Next Steps", cite o número.
-->

## Decisões que este PR trava

<!--
Uma por bloco, com o motivo. São elas que o revisor precisa concordar — o
diff é consequência.

Se alguma premissa do DESIGN.md caiu durante a execução, diga qual e por quê.
Aconteceu antes (OQ11, OQ13) e é resultado legítimo, não desvio.
-->

## Verificado, não assumido

<!--
Os anexos do governo omitem limites que só o XSD tem, e números herdados de
plano erram. O que aqui foi conferido contra fonte primária — XSD, anexo,
resposta real do servidor — e o que continua sendo hipótese.
-->

- [ ] Se toca leiaute: validado contra `Schemas/`, não só contra o anexo
- [ ] Se toca catálogo: `--conferir` roda e o arquivo versionado bate com o anexo
- [ ] Se toca assinatura: o documento assinado sobrevive ao caminho completo
      (assinar → gzip → base64 → decodificar → descomprimir → verificar) **sem
      re-serialização**, nos dois perfis

## Guardas por mutação

<!--
Toda guarda nova passa por mutação: reintroduzir o defeito e confirmar que o
teste quebra. Guarda que não quebra nada é guarda vazia — já aconteceu duas
vezes neste repo, e nas duas a mutação foi quem contou.

Liste o que foi mutado e o que morreu. Se alguma mutação não matou nada, diga
o que o teste passou a cobrir.
-->

| mutação | testes que morreram |
|---|---|
|  |  |

## Checagens

- [ ] `pytest` verde
- [ ] `ruff check` e `ruff format --check` limpos
- [ ] `mypy --strict` limpo
- [ ] Exemplo novo de README foi **executado**, não escrito
- [ ] `DESIGN.md` atualizado se o roadmap, uma OQ ou uma premissa mudou

## Achados abertos

<!--
O que este PR sabe que ainda está errado ou incompleto. Deixar registrado aqui
é melhor que descobrir depois do merge — e melhor que segurar o PR.
-->
