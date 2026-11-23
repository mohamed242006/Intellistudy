"""Labelled retrieval queries over the files in ``data/uploads`` (the evaluation corpus).

Three kinds of query:

* ``answerable`` - the material contains the answer. A hit counts as correct when it comes from
  ``file`` (substring of the file name) and its text contains one of ``contains`` or its heading
  path contains ``heading`` (all case-insensitive). Bibliography sections never count.
* ``out_of_domain`` - unrelated to any document; retrieval should report that nothing relevant
  was found.
* ``near_miss`` - about a topic the corpus covers but asking for a fact it does not contain
  (for example the tuition fee in an admission deck). Retrieval alone cannot reliably refuse
  these; they are reported separately and are the answer layer's job.

Labels were written by hand from the document contents (see docs/e2e_validation_report.md for the
corpus). The set is small: treat percentages as indications, not guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EvalQuery:
    id: str
    query: str
    kind: str  # answerable | out_of_domain | near_miss
    file: str = ""
    contains: tuple[str, ...] = ()
    heading: str = ""
    allow_references: bool = False
    tags: tuple[str, ...] = field(default=())


def _a(id_: str, query: str, file: str, *, contains: tuple[str, ...] = (), heading: str = "", tags: tuple[str, ...] = ()) -> EvalQuery:
    return EvalQuery(id_, query, "answerable", file, contains, heading, tags=tags)


ANSWERABLE: tuple[EvalQuery, ...] = (
    # --- Aspect-Oriented lectures (PDF) ---
    _a("a01", "What is the principle of separation of concerns?", "1-Introduction", heading="separation of concerns"),
    _a("a02", "What types of stakeholder concerns are there?", "1-Introduction", heading="stakeholder concerns"),
    _a("a03", "What are code scattering and code tangling?", "1-Introduction", heading="tangling"),
    _a("a04", "How is the Aspect-Oriented course assessed?", "1-Introduction", heading="assessment criteria"),
    _a("a05", "What does structured programming focus on?", "1-Introduction", contains=("structured programming",)),
    _a("a06", "What cross-cutting concerns does the Apache Tomcat example show?", "1-Introduction", contains=("tomcat",)),
    _a("a07", "What is a pointcut?", "2-Concepts", heading="pointcuts"),
    _a("a08", "What is advice in aspect-oriented programming?", "2-Concepts", heading="advice"),
    _a("a09", "What are the advantages of aspects?", "2-Concepts", heading="advantages of aspects"),
    _a("a10", "How does aspect weaving work?", "2-Concepts", heading="aspect weaving"),
    _a("a11", "Give an example of an authentication aspect.", "2-Concepts", heading="authentication aspect"),
    _a("a12", "What is a join point?", "2-Concepts", contains=("join point",)),
    _a("a13", "How is synchronization separated from buffer functionality?", "2-Concepts", heading="synchronized buffer"),
    _a("a14", "What is explicit invocation in the hospital system example?", "2-Concepts", heading="explicit invocation"),
    # --- IntelliStudy proposal (PDF) ---
    _a("a15", "What development methodology does the project follow?", "final_proposal", contains=("agile",)),
    _a("a16", "How are quiz questions generated and validated?", "final_proposal", heading="question generation"),
    _a("a17", "What are the steps of the end-to-end workflow?", "final_proposal", heading="end-to-end workflow"),
    _a("a18", "How are student privacy and uploaded materials protected?", "final_proposal", heading="privacy"),
    _a("a19", "What does the adaptive learning layer do?", "final_proposal", heading="adaptive learning layer"),
    _a("a20", "What are the expected outcomes of the project?", "final_proposal", heading="expected outcomes"),
    _a("a21", "Who introduced retrieval-augmented generation?", "final_proposal", contains=("lewis et al",)),
    _a("a22", "What does the indexing layer do?", "final_proposal", heading="indexing layer"),
    _a("a23", "What study recommendations does the system give?", "final_proposal", contains=("study recommendations",)),
    # --- Cryptography decks (PPTX) ---
    _a("a24", "What is the difference between passive and active attacks?", "Section 01", contains=("passive attack",)),
    _a("a25", "How can encryption techniques be classified?", "Section 01", heading="encryption techniques"),
    _a("a26", "What is the difference between computer security and network security?", "Section 01", contains=("network security",)),
    _a("a27", "How does the Playfair cipher work?", "Section 02", heading="playfair"),
    _a("a28", "How is the Caesar cipher computed?", "Section 02", heading="caesar"),
    _a("a29", "What is the one-time pad?", "Section 03", contains=("one-time",)),
    # a30: the explanation is in "Section 02" slide 12, not in Section 03 (which only names the cipher). Kept unchanged so
    # the published retrieval numbers stay reproducible; the answer gold (answer_gold._A30_GOLD) uses Section 02.
    _a("a30", "How does the Hill cipher use a key matrix?", "Section 03", contains=("hill",)),
    # --- Software performance evaluation (PPTX) ---
    _a("a31", "Why use simulation to evaluate performance?", "SPE_l1", heading="why use it"),
    _a("a32", "How is the exponential distribution related to the Poisson process?", "SPE_l1", heading="exp-distribution"),
    _a("a33", "How can a simulation model be verified?", "SPE_l1", heading="model verification"),
    _a("a34", "What is the state of the system in queueing terminology?", "SPE_l1", heading="terminology and notation"),
    _a("a35", "What did the county hospital queueing results show?", "SPE_l1", heading="county hospital"),
    # --- DOCX samples ---
    _a("a36", "How is inline text formatting demonstrated?", "sample1", heading="text formatting"),
    _a("a37", "How does the document handle tables in Word?", "sample1", heading="tables"),
    _a("a38", "How are page margins defined?", "large-document", contains=("page margins define",)),
    _a("a39", "What does the regular expression pattern a.c match?", "large-document", contains=("any single character",)),
    _a("a40", "What is VBA?", "large-document", contains=("visual basic for applications",)),
    # --- small scanned / OCR documents ---
    _a("a41", "Who is the project supervisor?", "test2.pdf", contains=("gamal ibrahim",)),
    _a("a42", "Who are the team members?", "test2.pdf", contains=("abdulrahman",)),
    _a("a43", "What is IntelliStudy?", "test2.pdf", contains=("educational web platform",)),
    _a("a44", "What is the motivation of the project?", "test.pdf", heading="motivation"),
    # --- research papers (PDF) ---
    _a("a45", "Is K-injectivity a local property over a noetherian ring?", "hard_PDF_7", heading="local nature"),
    _a("a46", "What is the delta set of a numerical monoid generated by an arithmetic sequence?", "hard_PDF_2", contains=("delta set",)),
    _a("a47", "What is the Hassanzadeh-Nasrollah Nejad-Simis conjecture on Euler conductors?", "hard_PDF_10", contains=("conjecture",)),
    _a("a48", "When is a standard graded ring almost Gorenstein?", "hard_PDF_3", contains=("almost gorenstein",), tags=("references_trap",)),
    _a("a49", "What is proved about the injective dimension of the conormal module?", "hard_PDF_5", contains=("conormal",), tags=("references_trap",)),
    _a("a50", "What are Liouvillian first integrals of differential equations?", "hard_PDF_9", contains=("liouvillian",)),
    _a("a51", "How do Poisson isocurvature perturbations affect induced gravitational waves?", "hard_PDF_1.pdf", contains=("isocurvature",)),
    # Observed failures (E2E-10): the References page outranked the abstract for these exact wordings.
    _a("a52", "What is an almost Gorenstein ring?", "hard_PDF_3", contains=("almost gorenstein",), tags=("references_trap",)),
    _a("a53", "What is the injective dimension of the conormal module?", "hard_PDF_5", contains=("conormal",), tags=("references_trap",)),
)

_OOD = (
    "How do I bake a chocolate cake?",
    "Who won the football world cup in 2018?",
    "What is the weather in Cairo today?",
    "Explain the plot of Hamlet.",
    "How do I change a flat tire on my car?",
    "What is the capital of Australia?",
    "Give me a recipe for pasta carbonara.",
    "How many calories are in a banana?",
    "What is the stock price of Tesla?",
    "How do I train a dog to sit?",
    "Who painted the Mona Lisa?",
    "Translate good morning into Japanese.",
    "How do vaccines work?",
    "What are the symptoms of the flu?",
    "Who is the president of France?",
    "What are good places for tourists in Rome?",
    "How do I file taxes in Canada?",
    "What is the plot of the movie Titanic?",
    "How do I knit a scarf?",
    "What is the best smartphone to buy this year?",
    "Explain the rules of chess.",
    "How long should I boil an egg?",
    "What is the tallest mountain in the world?",
    "Recommend a good workout routine for beginners.",
)

OUT_OF_DOMAIN: tuple[EvalQuery, ...] = tuple(
    EvalQuery(f"o{i + 1:02d}", q, "out_of_domain") for i, q in enumerate(_OOD)
)

_NEAR = (
    "What is the tuition fee at Crimswest University?",
    "What GPA is required for admission to Crimswest University?",
    "Who is the dean of the Faculty of Engineering at Ain Shams University?",
    "How much does an IntelliStudy subscription cost per month?",
    "What is the final exam date of the Aspect-Oriented course?",
    "Who is the CEO of IntelliStudy?",
    "What is the AES block size and how many rounds does it use?",
    "What is the time complexity of breaking the Playfair cipher by brute force?",
    "What is the phone number of the admissions office?",
    "Which programming language was the IntelliStudy backend written in during the first sprint?",
)

NEAR_MISS: tuple[EvalQuery, ...] = tuple(
    EvalQuery(f"n{i + 1:02d}", q, "near_miss") for i, q in enumerate(_NEAR)
)

ALL: tuple[EvalQuery, ...] = ANSWERABLE + OUT_OF_DOMAIN + NEAR_MISS

# Files excluded from the evaluation corpus: synthetic filler (13k identical-style chunks), padding
# documents, and duplicated paragraphs. They would dominate the index without adding questions.
EXCLUDED_FILES: tuple[str, ...] = ("sample-5mb.docx", "sample-docx-files-sample4.docx", "spytm_Medium")
