# Dale Schuurmans — Chronological Overview

_Chronological overview · 3 talks · 2019–2025_

Dale Schuurmans has spent six years telling the AI community it is thinking about its own tools wrong. Here is the arc, era by era.

In 2019, Schuurmans drilled into the neglected basement of reinforcement learning, or RL. He argued that the standard way the field teaches RL hides a dangerous simplification. The agent-environment loop — the diagram every textbook opens with — makes the problem look clean. Underneath that picture sit layers of complexity. And beneath all of them sits a problem so basic it barely looks like RL at all. One-step batch policy optimization. You have a fixed dataset. You want a better policy. That is it. Schuurmans called it the sub-basement — a machine learning 101 problem that never appears in machine learning 101.

His target was the default optimization objective. Expected reward sounds reasonable. But it creates a training landscape that is flat, uninformative, and almost impossible to navigate. Gradients vanish. Plateaus stretch in every direction. Importance correction, the theorist's favorite fix, makes things worse — unbiased in theory, catastrophic in practice, because a few extreme samples dominate the entire estimate. Schuurmans argued that researchers already know better from supervised learning, where surrogates and Bayesian methods are standard. They just never carry those tools downstairs into RL.

> [**0:23**](https://www.youtube.com/watch?v=373_zVWceqA&t=23s) · _DLRLSS 2019 - Optimization in RL - Dale Schuurmans_ · 2019-10-15
>
> this picture this is the single most dangerous picture in all of AI every introduction to RL starts with this picture and the reason it's dangerous is that there is a deception this makes the RL problem look simple

Five years later, the framing widens dramatically. By mid-2024, Schuurmans was no longer focused on RL optimization alone. A chain of surprises — in-context learning, instruction following, chain-of-thought prompting — none of them designed or anticipated — had convinced him that large language models are not interesting because of language at all. They are interesting because they are a new kind of computer. One that was computationally universal even before training began.

> [**28:22**](https://www.youtube.com/watch?v=YnMqbpdHcaY&t=1702s) · _ICAPS 2024 Keynote: Dale Schuurmans on "Computing…_ · 2024-07-02
>
> an llm it's not interesting because of natural language it's interesting because is a new type of computer I think and it's a new type of computer that uh actually if necessary can simulate a classical formula uh formal machine but allows us you know new modes of interaction that were not available to us previously

He went further. Computational universality, he claimed, was already present at random initialization. A randomly initialized transformer can simulate any computation. Training did not create that ability. Training simply built a human interface — a way for people to communicate with the machine through natural language. The purpose of all that next-token prediction was just to make the input-output behavior understandable to us.

But frustration lurked underneath the excitement. Models could describe every search algorithm by name — A-star, breadth-first, bidirectional — and still fail at basic block-stacking puzzles. They held declarative knowledge and procedural execution in separate rooms with no door between them. Schuurmans framed this era as an open frontier. Not a battle between formal and informal computing, but a space nobody yet understood. The optimism was real — and short-lived.

By 2025, the tone sharpened into warning. Schuurmans arrived with impossibility results. Standard supervised learning could never have solved grade-school math benchmarks — not with more data, not with bigger models. The problem is computational, not statistical. A standard transformer gets a fixed number of operations per output token. Solving a math problem requires computation that scales with the problem's length. You cannot compress a linear-time algorithm into a constant compute budget. No amount of training examples changes that.

Chain-of-thought works because it changes the budget, not because it teaches better reasoning. Each generated token becomes a processing step. Policy gradient methods beat value-based RL for the same reason — they avoid computational gaps in the training signal. Value networks try to shortcut multi-step reasoning into a single number. The math does not allow it. And when training data skips intermediate steps, the model learns to guess rather than compute.

> [**1:03:19**](https://www.youtube.com/watch?v=yGLoWZP1MyA&t=3799s) · _Dale Schuurmans, Language Models and Computation …_ · 2025-08-25
>
> machine learning is awesome. Reinforcement learning even more so, but computer science matters. Especially when you're trying to train LLMs to to serve a whole range of problem instances. You are now confronted with the laws of computation.

He called current AI progress "the pursuit of mediocrity" — compiling inefficient algorithms inefficiently. It works on benchmarks. It scales, to a point. But it is not the kind of engineering that survives contact with genuinely hard problems.

Through every era, one thread holds. Schuurmans insists that the field's failures are not data problems or scale problems. They are thinking problems. Researchers reach for more data when they should reach for a different objective. They blame distribution shift when they should blame complexity class. In 2019, it was about RL optimization. In 2024, about what kind of machine an LLM really is. In 2025, about the laws that govern all computation. The targets change. The conviction does not. If it does not look right, it is not right. Think about it.

## Source talks

- [Dale Schuurmans, Language Models and Computation - RLC 2025](https://www.youtube.com/watch?v=yGLoWZP1MyA) — 2025-08-25
- [ICAPS 2024 Keynote: Dale Schuurmans on "Computing and Planning with Large Generative Models"](https://www.youtube.com/watch?v=YnMqbpdHcaY) — 2024-07-02
- [DLRLSS 2019 - Optimization in RL - Dale Schuurmans](https://www.youtube.com/watch?v=373_zVWceqA) — 2019-10-15
