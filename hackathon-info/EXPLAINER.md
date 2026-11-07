# Euodos, explained

A plain-language walkthrough to tell anyone what Euodos is, how it works and why it matters.

## In one sentence

When someone offers Habitat for Humanity land, Euodos answers the three questions that decide whether homes get built: **which law lets us build here and how fast, can the families afford and keep the homes, and who pays.** It answers them in one sitting, with a source behind every number.

## The problem (Impact Lab Lane 2, Clear it)

- Affordable homes in Orange County take about **4 years** from finding land to handing over keys.
- A faster path exists: land that is already allowed, a **ministerial** approval (meet the written rules and the city must say yes, with no hearing) and state-approved plans.
- The hard part is finding that path. There are seven possible legal routes, 34 cities each with their own forms, and city documents that still cite renumbered statutes. Every month of waiting costs money.

## The user

Maria (a made-up persona) runs real estate at Habitat for Humanity of Orange County. Crossline Church in Laguna Hills offers its parking lot. It is a real public parcel, APN 588-081-21. Her board asks: **can 30 families move in within two years?**

## What she does in the app

1. **Sign in.** Each session gets its own private copy of the scenario.
2. **The offer.** A neural network (a U-Net) reads the lot from real aerial imagery: **45,450 m²** of parking, room for **30 townhomes**. The side panel lists every public dataset used and the CNN's model card.
3. **The path.** **Seven legal paths** are tested against this parcel, each with its law, clock and every test marked met, to verify or fails.
   - **SB 4** (by-right building on church land) is the fastest fit, with 3 facts still to verify.
   - **4 of 7** paths cannot fit 30 homes.
   - Change the project to 8 homes and SB 684 opens up. Pick a path and the clock follows it.
4. **The clock.** The project is a chain of steps, and the clock is the longest chain. **4.2 years becomes 2.4.** Three moves do it:
   - the site is screened in minutes, not 6 months
   - SB 4 replaces hearings and environmental review
   - funding and family selection start on day one instead of after approval
5. **Families.** 30 households with incomes from real 2024 mortgage records:
   - **30 of 30** would be turned down by a regular bank.
   - Euodos designs each family's mortgage to **keep the home for 10 years**, and an edit to any income recomputes live.
6. **Who pays.** The money gap is added up home by home: **$5.4M** of philanthropy versus **$6.8M** with standard loans.
7. **Ten years.** The same families live the same job losses and repair bills under three loan types. **22 of 30** are expected to keep their homes with Euodos, versus **7.5** on market loans.

There is also a **one-page summary** for the board and a **source button** on every headline number.

## The AI inside

- **A team of Claude agents.** A Director (Opus 5.5) hands work to Land, Family and Capital leads, who hand it to analysts and underwriters (Sonnet 5.5), working in parallel. Type a question and watch the hierarchy light up live.
- **What the agents run.** The real models through a tool server (MCP). They write and run their own analysis code in a locked sandbox with no internet.
- **Self-checking.** Automatic graders fail any brief with a made-up link or an undisclosed assumption. A fixed promotion gate decides when a model or playbook improves. For example, a challenger CNN scoring +0.003 IoU was rejected as noise.
- **Works offline.** Without an API key, a stand-in policy drives the same agents, tools and graders.

## Why it is different

- It answers **one real address**, not averages.
- **Time is calculated, not guessed.** A step only saves time if it is on the longest chain.
- It measures **keeping** the home, not just getting it.
- **Unknowns stay unknown.** Zoning, title and fire and flood screens are marked "to verify".
- **Fair by design.** Race is never a model input, but every model reports how fair it is across groups.
- **Scales.** A new Habitat region is one settings file plus one pipeline command.

## Honest limits

- Household finances and risk rates are assumptions; there is no public data on how Habitat loans perform.
- The church tag comes from OpenStreetMap, not a title record.
- The SB 684 clock has not been read in detail, so the app says "unknown".
- Plan-check rounds and utility sign-offs are not yet separate delays.

## How it fits the judging

| Area | Evidence |
|---|---|
| Impact | A Habitat project manager could triage land offers with it next month |
| Works | Real parcel, real imagery, real mortgage data, sources on screen |
| Scale | A new region is one settings file |
| Innovation | Legal path, clock, families and money in one connected model |
