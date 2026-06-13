# Failure attribution (llmq+embed vs llmq+cite+embed+freq)

Classification per claim: where does the pipeline lose the gold paper —
never retrieved (`retrieval_miss`), retrieved but ranked below 5
(`rank_miss`), or in the top five (`hit@5`). Ranking here is the
no-judge configuration, so the table isolates retrieval and the
citation-frequency signal from LLM behaviour.

| claim | before: outcome | before: rank | after: outcome | after: rank |
|---|---|---|---|---|
| attention | rank_miss | 50 | hit@5 | 1 |
| transformer | retrieval_miss | — | hit@5 | 2 |
| gan | rank_miss | 174 | rank_miss | 29 |
| resnet | retrieval_miss | — | hit@5 | 1 |
| dropout | hit@5 | 2 | hit@5 | 1 |
| batchnorm | hit@5 | 1 | hit@5 | 1 |
| adam | rank_miss | 181 | rank_miss | 84 |
| word2vec | retrieval_miss | — | hit@5 | 1 |
| bert | rank_miss | 20 | hit@5 | 3 |
| cot | hit@5 | 1 | hit@5 | 3 |
| ddpm | rank_miss | 41 | hit@5 | 1 |
| vae | rank_miss | 10 | hit@5 | 1 |
| seq2seq | rank_miss | 11 | hit@5 | 1 |
| lstm | rank_miss | 15 | hit@5 | 1 |
| gpt3 | rank_miss | 25 | hit@5 | 1 |
| rlhf | hit@5 | 1 | hit@5 | 1 |
| clip | retrieval_miss | — | hit@5 | 1 |
| vit | hit@5 | 1 | hit@5 | 1 |
| distillation | retrieval_miss | — | hit@5 | 1 |
| lora | rank_miss | 69 | rank_miss | 10 |
| rag | rank_miss | 7 | hit@5 | 1 |
| ppo | retrieval_miss | — | hit@5 | 1 |
| layernorm | hit@5 | 2 | hit@5 | 2 |
| unet | rank_miss | 11 | hit@5 | 1 |
| dqn | rank_miss | 23 | hit@5 | 5 |
| scaling | hit@5 | 1 | hit@5 | 1 |
| elmo | hit@5 | 1 | hit@5 | 2 |
| alphago | hit@5 | 2 | hit@5 | 1 |

## Transition summary

| before → after | claims |
|---|---|
| rank_miss → hit@5 | 10 |
| hit@5 → hit@5 | 9 |
| retrieval_miss → hit@5 | 6 |
| rank_miss → rank_miss | 3 |
