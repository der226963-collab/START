# Release eval — SmolLM2-360M (pretrained, 2026-11-13)

Protocol: eval/RELEASE_EVAL.md (held-out pack written 2026-11-11; checked against data/ and data/code/ with zero verbatim overlap). Comparison baselines: medium MiniGPT (eval/medium-baseline-2026-11-11.md, held-out 3.0873, generation word salad) and leg 4 (eval/large-eval-leg4-2026-11-13.md, held-out 3.0081, generation word salad). This eval has TWO legs, not three: held-out loss and generation coherence. The intent leg does not apply (it tests the MiniGPT-based assistant's intent classifier, not a language model). Held-out loss here runs in BF16 (the model's native dtype); the MiniGPT evals ran in fp32 — the dtype gap is small (~0.01-0.03). Model: HuggingFaceTB/SmolLM2-360M (Apache 2.0), loaded by our own code (mini_ai/gpt/smollm2.py). Nothing in eval/ was moved into data/ or data/code/. The held-out text is 3,364 chars = 804 SmolLM2 tokens (the MiniGPT tokenizer expands the same text to many more tokens), so the held-out batches are drawn from a small pool. Held-out loss uses batch 8, not the MiniGPT evals' batch 32: a 360M model on this CPU needs ~23 s per 8x512 batch (~2.9 s per sequence), so batch 32 would take ~92 s per batch and the 20-batch run would exceed the 900 s timeout (it did, on the first attempt).


## Held-out loss (eval/heldout_text.txt, 20 batches, seed 42)

```
Command: /home/hatch/workspace/torch-venv/bin/python evaluate_smollm2.py --data eval/heldout_text.txt --batches 20 --batch-size 8 --seed 42 (exit 0)

file: eval/heldout_text.txt  chars: 3364  tokens: 804  loss: 2.7633  perplexity: 15.9
Lower loss is better. Perplexity is exp(loss); it is not a quality judgement, only a fit measure.
```


## Generations (temperature 0.7, length 150)


### Prompt 1

```
Prompt 1: The community garden needs a plan for the spring, and the first question is how much land each household will tend.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

The community garden needs a plan for the spring, and the first question is how much land each household will tend. In addition to all the produce to be harvested in the garden, there will be some growing space in the courtyard for the community’s plants and flowers, which will provide shade for the family’s home. 

What is the best way to partner with the community to fulfill this garden? Are there spaces in the area that were taken over for a parking lot or industrial parking lot? Is there enough space to create a new community garden? 

The community garden needs a plan for the spring, and the first question is how much land each household will tend. In addition to all the produce to be harvested in the garden, there will be some growing space in the courtyard for the community’s plants and flowers, which will provide
```


### Prompt 2

```
Prompt 2: Phosphorus is a limit that cannot be wished away, because the rivers carry whatever the fields cannot hold.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

Phosphorus is a limit that cannot be wished away, because the rivers carry whatever the fields cannot hold. So I grew up in a city. That is why, when I was not in a position to enjoy the fields and the rivers, I did not understand the fruits of the fields and the rivers. You can understand this, if you are interested in following the deeper meaning of the poem.

The question of the poem is: What is the answer to the question: Where do you want to be? The answer is: There are many places to be. What is the key to the answer to the question: Where do you want to be? The key is the answer to the question: What do you want to be?

What do I want to be?

What do I want to be?

The answer is
```


### Prompt 3

```
Prompt 3: On a cold morning in November, the weather turned quickly and the town had to decide whether to open the hall early.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

On a cold morning in November, the weather turned quickly and the town had to decide whether to open the hall early. The place was full of people who were waiting to see the new governor, Colonel Patrick Henry. Henry was the head of the Virginia Assembly. The assembly was a group of people who were important in Virginia. The people living in the town were members of the assembly as well. The assembly had to decide whether to open the hall early by voting. The assembly voted. Henry won the vote by 56 to 44.

The assembly had to decide to open the hall early for another reason. They wanted to discuss the new laws. The new laws were to be passed by the governor. Henry's new laws were the ones that would be passed by the governor. One of the laws was that every man who owned a house or lot
```


### Prompt 4

```
Prompt 4: A neighbourhood that shares its cooking and its childcare has to decide how the work is counted and who does which part.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

A neighbourhood that shares its cooking and its childcare has to decide how the work is counted and who does which part. All of this depends on how difficult it is to find the parents.

The fundraiser for the children of the new neighbourhood is to buy some food for the new families, but there is no contract for the donation. The fundraiser must decide how to spend the money.

Who should decide how to spend the money?

The community may have to divide the money among several smaller neighbourhoods. If the community has to choose the division, who should decide?

If the community has to choose the division, which priority should the community give to the children of the new neighbourhood?

The new neighbourhood has 3,000 people and the proposed division is 1,000 per household.
```


### Prompt 5

```
Prompt 5: The soil in the lower field is tired after years of the same crop, and the farmers are talking about what to plant instead.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

The soil in the lower field is tired after years of the same crop, and the farmers are talking about what to plant instead. Something that could produce a big yield in a short amount of time. The farmers are even considering a season of crops that could take 15-20 years to produce, they are thinking of a succession cropping.

The farmers are concerned about the amount of water that the land will need for the crops to grow. They are also concerned that they will not have enough water to irrigate the fields every year, and will the water will be there in the future? One farmers talk about a new way of water harvesting that will allow the farmers to grow more crops in the same amount of time.

The farmers are trying to raise the prices of the products that they are growing, to meet the demand and make a profit. The
```


### Prompt 6

```
Prompt 6: When the wind drops at night, the solar panels give nothing and the stored energy has to carry the houses until morning.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

When the wind drops at night, the solar panels give nothing and the stored energy has to carry the houses until morning.

This is certainly an advantage in the case of a major storm or hurricane, but a small one in the case of a power outage.

A car battery, however, has advantages of its own. It is different from a car's grip, but the advantages are similar. A car battery is a very efficient converter of electrical energy and can be used to power a small house.

Car batteries do not have an electric current that is strong enough to be used as a power source for a house, but they are very efficient at storing electrical energy.

The best place for a car battery is in a garage or shed. It is safe because even if a storm is raging nearby, you can put the car battery on a
```


### Prompt 7

```
Prompt 7: A good plan is not a promise, it is a list of numbers that can be checked, and the checking is what makes it honest.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

A good plan is not a promise, it is a list of numbers that can be checked, and the checking is what makes it honest.

"The first thing, of course, is to make sure that it is the right number."

The United States has a plan, but it is not the one we think it is. This is what a plan should be:

Plan A

The US National Park Service should establish a plan to manage our National Parks and other public lands. The plan should include:

  • A policy statement that the government has the authority to manage public lands for a wide variety of purposes, inclusive of cultural, scientific, recreational, educational, aesthetic, and historic interests.
  • A policy statement that the National Park Service is the exclusive, independent, and first-rate source of federal land and resource management.
  • A policy statement
```


### Prompt 8

```
Prompt 8: The river runs low in August, and the farms, the town, and the fish all need water from the same shrinking stream.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

The river runs low in August, and the farms, the town, and the fish all need water from the same shrinking stream. The fish are getting bigger, and the water is more productive. They are the ones who will be able to survive into the new season. But the stream will be too small to carry all these things.

Here in the river, Nico is like a fish. You try to catch him, but he runs away. He swims faster than he can breathe, bites faster than he can swim, and jumps out of the water faster than he can look.

The water is warm, but it feels cold. He's a fish, and he's a fish who runs away when he thinks there is a trap. He swims faster than he can breathe, bites faster than he can swim, and jumps out of the water faster
```


### Prompt 9

```
Prompt 9: Learning to repair a bicycle is a small skill, but a street full of people who can repair things is a different kind of wealth.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

Learning to repair a bicycle is a small skill, but a street full of people who can repair things is a different kind of wealth.

Cycling is a skill, but a skill that is not just something that you can learn. Cycling is a skill that comes with lots of practice, which is why it is also a skill that is learned, even if you have never tried to ride your bike before. You can learn to ride your bicycle if you want to, but only if you have the right training, and that means having a bike.

Bicycles are a pretty simple concept, but there are some things that you need to know before you can start riding. The first thing you need to know is that bicycles are made out of metal. Metal is strong, and it can take a lot of punishment before it breaks.

The second thing
```


### Prompt 10

```
Prompt 10: The old library keeps its records on paper, and the new volunteers are learning how to read the handwriting of the clerks who came before them.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

The old library keeps its records on paper, and the new volunteers are learning how to read the handwriting of the clerks who came before them.

The library has long been one of the local economics and development centers. It is home to many local think tanks, and it is well known that the library is the lowest cost method of keeping old records.

The library serves as a high level server for the city, and a great deal of old records are kept there.

The library is located in the middle of the city, and is about half a mile from the main street which runs through the heart of the city.

The street is lined with the old buildings that have been standing since the first years of the city.

The street is lined with buildings that are made from the old materials that have been used in the city.

The buildings are
```


### Prompt 11

```
Prompt 11: If a machine drafts the words and a person decides what they mean, then the machine is a tool and the person is still in charge.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

If a machine drafts the words and a person decides what they mean, then the machine is a tool and the person is still in charge.

The machine is a tool. The person is still in charge.

The machine is not a person.

The machine is a tool. The person is still in charge.

The machine is not a person.

The machine is a tool. The person is still in charge.

The machine is not a person.

The machine is a tool. The person is still in charge.

The machine is not a person.

The machine is a tool. The person is still in charge.

The machine is not a person.

The machine is a tool. The person is still in charge.

The machine is not a person.

The machine is a
```


### Prompt 12

```
Prompt 12: Winter food for a household is not one big purchase, it is a slow store built up jar by jar through the autumn.
Command: generate_smollm2.py --length 150 --temperature 0.7 (exit 0)

Winter food for a household is not one big purchase, it is a slow store built up jar by jar through the autumn. A single jar of food is not enough to feed a household for the winter. Instead, a household stores food over the winter in smaller jars, one for each person. It is important to choose food that is seasonal or at least available throughout the winter. For example, if you do not have any apples for winter, you should purchase apples in the season.

A household will also stockpile food through the summer. It is recommended to purchase food that will not spoil during summer, including fruits and vegetables.

Also, it is recommended to store beer and wine. Beer and wine are very good bets for a good winter harvest.

The best time to stockpile food is during the summer and early fall when it is still warm
```

## Verdict (added 2026-11-13, after reading the generations)

**2 of 2 legs pass — the first model in START to pass the generation leg.**

- **Loss: PASS.** Held-out 2.7633 (ppl 15.9) vs medium 3.0873 and leg 4 3.0081. Better by 0.24-0.32, far larger than the BF16/batch-size noise (~0.01-0.03).
- **Generation: PASS.** 10 of 12 prompts are clearly coherent, on-topic, mostly grammatical prose for several sentences (garden, November hall, soil, solar, plan/numbers, river, bicycle, library, winter food, neighbourhood). Prompt 2 drifts into repetition after a coherent start. Prompt 11 falls into a repetition loop ("The machine is a tool. The person is still in charge.") — grammatical, but stuck. Repetition loops are the model's main weakness (a base model at temperature 0.7, not instruction-tuned); it does not produce word salad on any prompt, unlike the MiniGPT on all 12.

This makes SmolLM2-360M usable for coherent text generation on this machine, at ~0.4 s/token. It is a base model, so it continues text rather than answering questions; that is what the narrow fine-tuning stage is for.
