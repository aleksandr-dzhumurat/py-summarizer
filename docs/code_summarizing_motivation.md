# Code agents need less context, not more 🤖

We throw entire codebases at LLMs and wonder why the output is mediocre.

The problem isn't the model. It's the context. 📦

---

I've been building **repo-summarizer** — a tool that extracts only what matters:

- 🦴 **Code skeleton**: imports, classes, function signatures (no bodies)
- 📞 **Call graph**: who calls whom, fully symbol-resolved
- 🌳 **Inheritance graph**: class hierarchies as edges

The result fits an entire repository into ~5% of its original token count — without losing the relationships that matter.

---

A few things I learned along the way:

⚡ **Dependencies are context too.** I replaced `networkx` with ~80 lines of pure Python. One fewer library for an agent to reason about.

🎯 **Symbol resolution is non-negotiable.** "calls `query_documents`" is useless. "calls `src.retrieval.query_documents`" lets an agent jump directly to the right file.

🔗 **Inheritance is a graph edge, not metadata.** Store it as an edge and a single query answers "what inherits from X?" for the whole repo.

---

Give a code agent a 50KB JSON instead of a 5MB codebase. Less context. Better answers. ✅

#AI #CodeAgents #LLM #SoftwareEngineering #DeveloperTools
