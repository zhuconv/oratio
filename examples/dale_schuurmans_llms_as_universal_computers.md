# Dale Schuurmans — Dale Schuurmans, Language Models and Computation - RLC 2025

_Short overview · ~5 min_

Dale Schuurmans is a computer scientist at Google DeepMind. He has a message for the AI community. You are thinking about language models all wrong.

His argument starts with failure. For years, researchers tried to teach language models basic arithmetic. Grade-school math. They used massive datasets. Larger models. Every trick in the supervised learning playbook. And none of it worked reliably. Most people assumed the fix was more data or smarter training. Schuurmans says that assumption was dead wrong. Not just ineffective — fundamentally impossible.

> [**4:55**](https://www.youtube.com/watch?v=yGLoWZP1MyA&t=295s) · _Dale Schuurmans, Language Models and Computation …_ · 2025-08-25
>
> the real lesson here is actually it's not just that it didn't work, it couldn't have worked. There was no possible way for this to have worked.

The reason comes from computer science, not machine learning. A transformer produces each token through a single forward pass. That is a fixed, constant-time operation. But solving a multi-step math problem requires linear time — work proportional to the number of steps. No amount of data can bridge that gap. You simply cannot compile a linear-time algorithm into a constant-time budget.

> [**7:42**](https://www.youtube.com/watch?v=yGLoWZP1MyA&t=462s) · _Dale Schuurmans, Language Models and Computation …_ · 2025-08-25
>
> If you're trying to compile a linear time algorithm into a constant time budget, there is no coverage issue. You could get data forever. This will never work. It's not a statistical problem. It's a computer science problem.

But Schuurmans doesn't stop at the impossibility result. He makes a far more surprising claim. Despite this per-token limitation, language models are already universal computers. Turing-complete, in the formal sense. You don't need a million-token context window. You don't even need training on language. A context window of just two tokens is enough. Even a randomly initialized, completely untrained transformer qualifies.

> [**20:10**](https://www.youtube.com/watch?v=yGLoWZP1MyA&t=1210s) · _Dale Schuurmans, Language Models and Computation …_ · 2025-08-25
>
> in fact training on natural language has nothing whatsoever to do with the computational universality of these models. Language is irrelevant for computation.

So all that internet pre-training? It doesn't grant the model computational power. It simply makes the input-output behavior legible to humans. Pre-training is an interface layer. A translation skin. Not an engine.

This reframes the question everyone keeps debating — can LLMs, large language models, actually reason? For Schuurmans, the answer is mathematically clear. These are universal computers. For any computable behavior, a prompt exists that will produce it. End of story. But the real problem is different, and much harder.

> [**25:34**](https://www.youtube.com/watch?v=yGLoWZP1MyA&t=1534s) · _Dale Schuurmans, Language Models and Computation …_ · 2025-08-25
>
> nobody knows how to program these models. They're not formal machines, right? They're they're you know output behavior is unpredictable to us. They seem to be useful and then they're not useful, right? It seems to be working and then it's not working, right?

Consider what this means in practice. The models know more about algorithms than most humans do. Ask one to explain dynamic programming and it will describe techniques far beyond any standard textbook. But ask it to actually execute that algorithm on a specific input? It stumbles. It fails. The model knows of the method without knowing how to faithfully apply it. That gap — between declarative knowledge and procedural execution — is where all the frustration lives.

Which brings us to the current generation of reasoning models. The ones built on chain-of-thought and reinforcement learning — or so the story goes. Schuurmans punctures that narrative. What's actually working is not sophisticated RL, reinforcement learning. It is policy gradient. On-policy, stochastic, simple. Value-based methods have been tried for years at major labs. They keep losing. And those long reasoning traces the models produce? They're not evidence of deep thought. They're closer to random walks that stumble onto correct answers.

> [**1:01:42**](https://www.youtube.com/watch?v=yGLoWZP1MyA&t=3702s) · _Dale Schuurmans, Language Models and Computation …_ · 2025-08-25
>
> I would argue we are indeed achieving success right now through the pursuit of mediocrity. But that's a good thing that the the the advantage is we are not pursuing unattainable goals. We are not trying to compile some super linear algorithmic problem into a constant circuit representation of that algorithm. We are just trying to compile into some constant circuit some very inefficient algorithm and we're compiling it very inefficiently and that's what's winning.

And this mediocrity is actually the only sound approach. The moment you reach for fancier methods — value functions, Thompson sampling, tree search — you reintroduce the constant-compute impossibility. You train the model to guess. And guessing does not scale.

The takeaway cuts against the grain of the current AI discourse. Machine learning is powerful. Reinforcement learning even more so. But the laws of computation don't bend to training budgets. You cannot throw data at a complexity barrier and expect it to yield. We have built universal computers that we barely know how to program. The path forward isn't bigger models or more data. It is learning to direct the extraordinary machines we have already built.

## Source

[Dale Schuurmans, Language Models and Computation - RLC 2025](https://www.youtube.com/watch?v=yGLoWZP1MyA)
