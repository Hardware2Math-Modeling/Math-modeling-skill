---
name: math-modeling-paper-writing
description: Use when validated mathematical modeling results need a paper or when already validated modeling material needs editorial revision; do not use when validation has not passed.
---

# Mathematical Modeling Paper Writing

Turn validation-passed modeling evidence into the requested deliverable without improving apparent completeness by inventing support.

## Input gate

Accept the current handoff and requested deliverable. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and normalize the handoff. Require the user-supplied absolute Python interpreter path recorded by preflight; if it is absent, stop and ask for it rather than selecting one. Proceed only when `state.validation_status` is `pass`, no input stage from problem analysis through validation remains in `state.invalidated_stages`, Gate 3 has a current auditable `confirmed` record, and every question has a current result contract whose `freeze_status` is `confirmed`. Paper writing itself may remain invalidated while this stage regenerates it. Editing an existing deliverable does not bypass this gate. If any prerequisite is absent or stale, return `needs_revision`, name the evidence gap, and do not draft finished prose, infer a value, or fill the gap.

## Required Chinese content contract

Use `zh-CN` by default. Add an English abstract only when a current verified template or competition manifest explicitly requires `english_abstract`; a request, convention, or fallback template is not sufficient.

Produce this exact semantic hierarchy and these titles:

```text
摘要
关键词
1 问题背景与重述
  1.1 问题背景
  1.2 问题重述
2 问题分析
3 模型假设
4 符号说明
5 模型的建立与求解
  5.1 第一问
    5.1.1 建模
    5.1.2 计算
  5.2 第二问
    5.2.1 建模
    5.2.2 计算
  ...
6 模型检验
7 模型评价与推广/改进
8 结论
附录 A 参考文献
附录 B 代码清单与关键代码
附录 C AI 使用说明与人工复核记录
附录 D 补充表格、推导和图表
```

Create one `5.x` block per canonical `Qn`, in question order. Every block contains exactly the `5.x.1 建模` and `5.x.2 计算` semantic slots; keep validation evidence in section 6 rather than adding a per-question third or fourth slot. Section 4 is exactly a three-column `符号 | 说明 | 单位` table.

The abstract begins with exactly two sentences in order: background plus affirmation that the problem exists, then what this paper completed. Follow them with exactly one natural paragraph per question. Each question paragraph starts with a summary sentence, describes the modeling steps, solution method, and necessary validation, and ends with the answer or frozen core quantitative conclusion. Put `关键词` immediately after the abstract. Do not add a generic closing or limitations paragraph to the abstract.

Build the structured content against [the paper-content schema](../math-modeling-paper-production/references/paper-content.schema.json), validate it with `scripts/paper_content.py`, and freeze it only when the validator reports no errors. Numerical claims cite a safe relative result-contract path and lowercase SHA-256; figure and table references resolve to current manifests with `status: verified`. Use `\\textbf{}` only in the abstract or for an evidence-backed important claim.

## Responsibilities

- Formal delivery is LaTeX only; Word is not a formal output. Confirm the language, length, audience, and required sections before drafting when those constraints are not already supplied.
- Ask for the template path before drafting and record this fixed priority for paper-production: user-supplied template, then an official template explicitly selected by the user, then a locally verified template, then the built-in fallback. Paper-production copies and uses the selected template; paper-writing does not modify a template installation in place.
- Build a traceable narrative from the problem, assumptions, model choice, solution, evidence, and validation. Keep claims within validated scope.
- Keep notation, equations, variable definitions, units, numerical precision, table and figure references, citations, and artifact paths mutually consistent.
- Include assumptions, limitations, uncertainty, failure domains, extrapolation boundaries, and rejected alternatives when they matter to interpretation.
- Report a missing citation, figure, calculation, or validation item directly. Preserve evidence gaps as gaps rather than inserting a plausible placeholder or unsupported number.
- Treat a fallback template as `fallback_non_submission`: it may support a draft, but never a submission-ready claim. Preserve a production target of 25–27 body pages and no more than 30 total pages. These counts come only from the compiled PDF: body pages run from section 1 through section 8, while total pages include the cover, abstract, body, and appendices. Paper-production performs compilation and page counting. Add only necessary derivation, analysis, validation, and limitations; never pad, add blank pages, manipulate font size, or use invisible content to meet a page count.

## Boundaries

Do not fabricate citations, data, equations, figures, computed values, artifacts, or validation results. Do not disguise an unvalidated draft as final. Do not invoke another skill. This stage does not independently announce completion of the full modeling task.

## Output

Return an updated handoff that preserves `task.statement`, `task.objectives`, and `task.constraints`, and set `state.current_stage` to `paper-writing`. Record the deliverable and all relative document, table, and figure paths in `artifacts`, and record traceability and consistency evidence in `result` and `quality.checks`. Put editorial or evidence gaps in `quality.warnings` and preserve an evidence-based `quality.confidence`. When the requested, supported deliverable is ready, set the stage status to `complete`, set `next.recommended_stage` to `paper-production`, explain why in `next.rationale`, and list any remaining defensible editorial actions in `next.alternatives`; the paper-production stage creates and checks the final artifact.
