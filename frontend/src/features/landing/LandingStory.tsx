import { motion } from "motion/react";
import { ArrowRight, ListTree, Quote, SlidersHorizontal } from "lucide-react";
import { Link } from "react-router-dom";

import { FlowChain } from "@/features/landing/FlowChain";
import { LandingItem, LandingSection } from "@/features/landing/LandingSection";
import { PipelineRail, type PipelineStage } from "@/features/landing/PipelineRail";
import { ProviderRouting } from "@/features/landing/ProviderRouting";
import { RetrievalNarrowing } from "@/features/landing/RetrievalNarrowing";
import { inViewOnce, sectionItem, sectionReveal } from "@/lib/motion";

/* Sections 02–09 of the entry experience.
 *
 * Split into its own module so it can be code-split away from the hero
 * (Phase 21): the first screen a visitor waits for does not include
 * the eight sections below it. This file loads while they are reading
 * the hero.
 *
 * Everything on this page is explanatory. Each stage, model and
 * component named below exists in the platform and is named the way
 * the codebase names it — but nothing here is read from a running
 * system. There is no live count, no status, no score, and no
 * assertion about performance or accuracy anywhere in this file. */

/** The real processing sequence, in order. Each description says what
 * that stage does to the work, not how well it does it. */
const PIPELINE: PipelineStage[] = [
  {
    name: "Collect",
    detail:
      "Documents are uploaded into a project and extracted to text — the project is the unit that owns them, so knowledge never leaks between pieces of work.",
  },
  {
    name: "Understand",
    detail:
      "A language model reads each document and records a profile of it: what it covers, the terms it uses, the entities it names, the language it is written in.",
  },
  {
    name: "Embed",
    detail:
      "Text is split into passages and embedded with BGE-M3, giving every passage a position in the same vector space a question will later be placed into.",
  },
  {
    name: "Retrieve",
    detail:
      "A question is embedded the same way, and the passages nearest to it are pulled back as candidates. Fast, approximate, and deliberately generous.",
  },
  {
    name: "Rerank",
    detail:
      "A cross-encoder reads each candidate against the question itself rather than comparing two summaries of meaning, and re-scores the whole set.",
  },
  {
    name: "Ground",
    detail:
      "A relevance gate discards passages too weak to support an answer. When nothing clears it, the run stops here and reports insufficient evidence rather than proceeding.",
  },
  {
    name: "Synthesize",
    detail:
      "The surviving evidence — and only that evidence — reaches the synthesis model, and every citation that comes back is validated against what was actually supplied.",
  },
];

/** What the document-understanding stage records for each document. */
const PROFILE_FIELDS = ["Summary", "Keywords", "Entities", "Topics", "Language"];

const WORKSPACE_FEATURES = [
  {
    icon: ListTree,
    title: "Pipeline timeline",
    body: "Every stage of a run, in the order it executed, with what each one produced.",
  },
  {
    icon: SlidersHorizontal,
    title: "Evidence funnel",
    body: "How many passages were retrieved, how many reached the model, and how many were cited — for that run.",
  },
  {
    icon: Quote,
    title: "Citation to source",
    body: "Open any citation to see the passage behind it, the document it came from, and how it scored.",
  },
];

export default function LandingStory() {
  return (
    <>
      {/* ---- 02 ---------------------------------------------------- */}
      <LandingSection
        index="02"
        eyebrow="The problem"
        heading="Collecting information was never the hard part."
        standfirst={
          <>
            Most organisations already hold far more material than anyone can read. The
            difficulty is not storage or search. It is knowing what your own documents
            actually say — and being able to show why you believe it.
          </>
        }
      >
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={inViewOnce}
          variants={sectionReveal}
          className="grid gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-3"
        >
          {[
            { title: "Search finds documents.", body: "You still have to read them." },
            {
              title: "Assistants generate text.",
              body: "Fluent, confident, and accountable to nothing you own.",
            },
            {
              title: "Neither shows its evidence.",
              body: "So neither can be checked, and neither can be trusted with a decision.",
            },
          ].map((item) => (
            <motion.div key={item.title} variants={sectionItem} className="bg-background p-7">
              <p className="font-display text-lg leading-snug tracking-tight text-foreground">
                {item.title}
              </p>
              <p className="mt-2.5 text-sm leading-relaxed text-muted-foreground">{item.body}</p>
            </motion.div>
          ))}
        </motion.div>
      </LandingSection>

      {/* ---- 03 ---------------------------------------------------- */}
      <LandingSection
        id="pipeline"
        index="03"
        eyebrow="What AIKDAP does"
        heading="One pipeline. Seven stages. Every one of them recorded."
        standfirst={
          <>
            A question entering AIKDAP passes through the same sequence every time, and each
            stage writes down what it did. That record is what makes a finished answer
            something you can take apart rather than something you have to accept.
          </>
        }
      >
        <PipelineRail stages={PIPELINE} />
      </LandingSection>

      {/* ---- 04 ---------------------------------------------------- */}
      <LandingSection
        index="04"
        eyebrow="AI understanding"
        heading="Every document is read before it is ever retrieved."
        standfirst={
          <>
            Extraction gives you text. AIKDAP also asks a language model what the document is,
            and keeps that profile beside it — so the knowledge base knows what it holds, not
            just that it holds something.
          </>
        }
      >
        <div className="flex flex-col gap-10">
          <FlowChain
            align="start"
            nodes={[
              { label: "Document", note: "As uploaded" },
              { label: "Extraction", note: "Text and structure" },
              { label: "Qwen understanding", note: "Reads the document", tone: "ai" },
              { label: "Document profile", note: "Stored with the asset", tone: "primary" },
            ]}
          />

          <LandingItem>
            <div className="rounded-xl border border-border bg-card/60 p-7">
              <p className="text-label uppercase text-muted-foreground">
                What the profile records
              </p>
              <ul className="mt-4 flex flex-wrap gap-2">
                {PROFILE_FIELDS.map((field) => (
                  <li
                    key={field}
                    className="rounded-md border border-border-strong/60 bg-sunken px-3 py-1.5 text-sm text-foreground"
                  >
                    {field}
                  </li>
                ))}
              </ul>
              <p className="mt-5 max-w-2xl text-sm leading-relaxed text-muted-foreground">
                Understanding and embedding are tracked separately, because they can fail
                separately. A document whose profile is still being written is shown as exactly
                that, rather than as finished.
              </p>
            </div>
          </LandingItem>
        </div>
      </LandingSection>

      {/* ---- 05 ---------------------------------------------------- */}
      <LandingSection
        index="05"
        eyebrow="Knowledge retrieval"
        heading="Retrieval is a filter, not a search box."
        standfirst={
          <>
            Semantic search is fast and approximate. A reranker is slow and precise. AIKDAP
            uses the first to gather candidates and the second to decide which of them are
            strong enough to be shown to a model at all.
          </>
        }
      >
        <div className="flex flex-col gap-14">
          <FlowChain
            align="start"
            nodes={[
              { label: "BGE-M3", note: "Passage embeddings" },
              { label: "Semantic retrieval", note: "Nearest candidates" },
              { label: "BGE reranker", note: "Re-scored against the question", tone: "ai" },
              { label: "Relevance gate", note: "Weak evidence discarded", tone: "primary" },
            ]}
          />
          <RetrievalNarrowing />
        </div>
      </LandingSection>

      {/* ---- 06 ---------------------------------------------------- */}
      <LandingSection
        id="grounding"
        index="06"
        eyebrow="Grounded intelligence"
        heading="An answer is only as good as the evidence it was allowed to use."
        standfirst={
          <>
            AIKDAP does not ask a model what it knows. It hands the model the passages that
            survived retrieval, and then holds the answer to them.
          </>
        }
      >
        <div className="flex flex-col gap-12">
          <FlowChain
            align="start"
            nodes={[
              { label: "Question" },
              { label: "Evidence", note: "Passages past the gate" },
              { label: "Synthesis", note: "Answer written from evidence", tone: "ai" },
              { label: "Citation validation", note: "Checked against what was supplied" },
              { label: "Grounded answer", tone: "primary" },
            ]}
          />

          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={inViewOnce}
            variants={sectionReveal}
            className="grid gap-5 md:grid-cols-2"
          >
            <motion.div
              variants={sectionItem}
              className="rounded-xl border border-border bg-card p-7"
            >
              <h3 className="font-display text-xl tracking-tight text-foreground">
                Citations are verified, not trusted
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                Every citation the model returns is matched back to a passage that was actually
                supplied to it. A citation pointing at something that was never in the evidence
                is rejected — it does not reach the page with a caveat attached to it.
              </p>
            </motion.div>

            <motion.div
              variants={sectionItem}
              className="rounded-xl border border-border bg-card p-7"
            >
              <h3 className="font-display text-xl tracking-tight text-foreground">
                Missing evidence is an answer
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                When nothing clears the relevance gate, the run reports insufficient evidence
                and stops. Answering anyway from a model&rsquo;s general knowledge would produce
                the one thing this platform exists to avoid.
              </p>
            </motion.div>
          </motion.div>
        </div>
      </LandingSection>

      {/* ---- 07 ---------------------------------------------------- */}
      <LandingSection
        id="resilience"
        index="07"
        eyebrow="Provider resilience"
        heading="The pipeline outlives any single provider."
        standfirst={
          <>
            Synthesis talks to an internal gateway rather than to a vendor. The gateway holds an
            ordered chain of providers and continues down it when one cannot serve a request, so
            a run completes — and the answer records which provider served it.
          </>
        }
      >
        <ProviderRouting />
      </LandingSection>

      {/* ---- 08 ---------------------------------------------------- */}
      <LandingSection
        index="08"
        eyebrow="Research workspace"
        heading="The workspace shows its working."
        standfirst={
          <>
            Every run is inspectable after the fact. The stages it executed, the passages that
            survived each of them, and the source behind each citation are all on the page —
            not folded away behind a summary.
          </>
        }
      >
        <motion.ul
          initial="hidden"
          whileInView="visible"
          viewport={inViewOnce}
          variants={sectionReveal}
          className="grid gap-5 md:grid-cols-3"
        >
          {WORKSPACE_FEATURES.map(({ icon: Icon, title, body }) => (
            <motion.li
              key={title}
              variants={sectionItem}
              className="rounded-xl border border-border bg-card p-7"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-ai/30 bg-ai/[0.08] text-ai">
                <Icon aria-hidden="true" className="h-4 w-4" />
              </span>
              <h3 className="mt-5 font-display text-lg tracking-tight text-foreground">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
            </motion.li>
          ))}
        </motion.ul>
      </LandingSection>

      {/* ---- 09 ---------------------------------------------------- */}
      <motion.section
        initial="hidden"
        whileInView="visible"
        viewport={inViewOnce}
        variants={sectionReveal}
        aria-label="Get started"
        className="relative border-t border-border/60 py-32 md:py-44"
      >
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center px-6 text-center md:px-10">
          <motion.h2
            variants={sectionItem}
            className="max-w-4xl font-display text-statement text-foreground"
          >
            Turn information
            <br />
            into intelligence.
          </motion.h2>

          <motion.div variants={sectionItem} className="mt-12">
            <Link
              to="/login"
              className="group inline-flex items-center gap-3 rounded-xl bg-foreground px-8 py-4 font-display text-base font-medium tracking-tight text-background transition-colors duration-200 hover:bg-primary hover:text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Enter AIKDAP
              <ArrowRight
                aria-hidden="true"
                className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1 motion-reduce:transition-none motion-reduce:group-hover:translate-x-0"
              />
            </Link>
          </motion.div>

          <motion.p
            variants={sectionItem}
            className="mt-10 max-w-md text-sm leading-relaxed text-muted-foreground"
          >
            Answers are grounded in your own documents. When the evidence isn&rsquo;t there,
            AIKDAP says so.
          </motion.p>
        </div>
      </motion.section>
    </>
  );
}
