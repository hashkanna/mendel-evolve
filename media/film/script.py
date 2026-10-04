"""The film's narration, one beat per voice clip. Visual cues in film.html refer to beats by id.

Every number is from RESULTS.md (as in media/narration.md, which was fact-checked on 4 October).
Each scene: (id, lead-in seconds before its first beat, [(beat id, text, pause after in seconds), ...], tail seconds).
"""

SCENES = [
    ("open", 1.2, [
        ("b1", "AI can now evolve algorithms.", 0.8),
        ("b2", "Systems like AlphaEvolve rewrite whole programs, over and over, and keep whatever scores highest.", 0.6),
    ], 0.4),
    ("problem", 0.5, [
        ("b3", "They find remarkable solutions. But afterwards, nobody can say which idea produced the result.", 0.7),
        ("b4", "About thirty percent of the lines they add are lines they had deleted before.", 0.8),
        ("b5", "It is Darwin without Mendel: selection, but no genes.", 0.6),
    ], 1.0),
    ("genes", 2.6, [
        ("b6", "MendelEvolve turns every idea a language model proposes into a gene: a named switch in the solver.", 0.7),
        ("b7", "The model only invents. Classical search tunes and recombines.", 0.7),
        ("b8", "And then we do what geneticists do. We knock each gene out, and measure what is lost.", 0.4),
    ], 1.2),
    ("packing", 0.6, [
        ("b9", "Circle packing, starting from OpenEvolve's own program, with no hints.", 1.6),
        ("b10", "It reaches the best known value.", 1.4),
        ("b11", "Which idea did it? Knock it out.", 1.4),
        ("b12", "On fresh seeds, without this one gene, the solver loses one point six seven. One idea carries the result.", 0.4),
    ], 1.2),
    ("sphere", 0.6, [
        ("b13", "Then, open mathematics. Problem sixty, from Tao and co-authors: points in a cube grid, with no five on a common sphere.", 1.2),
        ("b14", "MendelEvolve found larger sets than any published, at seventeen sizes.", 1.0),
        ("b15", "Each one verified by three independent exact checkers.", 0.4),
    ], 1.2),
    ("iso", 0.6, [
        ("b16", "Problem fifty-nine: fifty-eight points in a thirty-two by thirty-two grid, with no isosceles triangle.", 0.6),
        ("b17", "Two papers state that fifty-six is optimal.", 0.9),
        ("b18", "All thirty thousand, eight hundred and fifty-six triples check out, and DeepMind's own verifier accepts it.", 0.4),
    ], 1.2),
    ("twice", 0.6, [
        ("b19", "Then we turned the knockouts on our own records.", 0.6),
        ("b20", "The engine's quick screens said evolution had added nothing. They were too weak to see a fifth of a point.", 0.7),
        ("b21", "So we measured again, at record scale: six hundred paired runs per idea, both arms in the same container.", 0.9),
        ("b22", "The evolved solver is a quarter of a point better.", 0.9),
        ("b23", "And the best single idea was one the engine had thrown away. Rejected by the quick screen. "
                "Measured properly, it is worth between zero point one nine and zero point three one.", 0.4),
    ], 1.4),
    ("close", 0.8, [
        ("b24", "MendelEvolve. Evolve ideas, not programs. Then measure them at the scale that matters.", 0.6),
        ("b25", "Every result, and every certificate, is public.", 0.2),
    ], 3.6),
]

# The two-minute cut (Iterate's limit). Same beat ids, so film.html animates it unchanged.
SCENES_SHORT = [
    ("open", 0.8, [
        ("b1", "AI can now evolve algorithms.", 0.4),
        ("b2", "Systems like AlphaEvolve rewrite whole programs and keep the best.", 0.3),
    ], 0.2),
    ("problem", 0.3, [
        ("b3", "But nobody can say which idea produced the result.", 0.3),
        ("b4", "About thirty percent of the lines they add were deleted before.", 0.4),
        ("b5", "Darwin without Mendel: selection, but no genes.", 0.3),
    ], 0.6),
    ("genes", 2.0, [
        ("b6", "MendelEvolve turns every idea a model proposes into a gene: a named switch.", 0.3),
        ("b7", "The model only invents. Classical search tunes.", 0.3),
        ("b8", "Then, like geneticists, we knock each gene out and measure what is lost.", 0.3),
    ], 0.6),
    ("packing", 0.4, [
        ("b9", "Circle packing, from OpenEvolve's own starting program.", 1.2),
        ("b10", "It reaches the best known value.", 0.8),
        ("b11", "Which idea did it? Knock it out.", 1.0),
        ("b12", "It loses one point six seven. One gene carries it.", 0.3),
    ], 0.8),
    ("sphere", 0.4, [
        ("b13", "Problem sixty, from Tao and co-authors: no five points on a sphere.", 0.8),
        ("b14", "New lower bounds at seventeen sizes.", 0.6),
        ("b15", "Each checked by three independent checkers.", 0.3),
    ], 0.8),
    ("iso", 0.4, [
        ("b16", "Problem fifty-nine: fifty-eight points with no isosceles triangle.", 0.3),
        ("b17", "Two papers state fifty-six is optimal.", 0.5),
        ("b18", "All thirty thousand, eight hundred and fifty-six triples check out.", 0.3),
    ], 0.8),
    ("twice", 0.4, [
        ("b19", "Then we knocked out our own records.", 0.3),
        ("b20", "Quick screens said evolution added nothing.", 0.4),
        ("b21", "At record scale, six hundred paired runs per idea:", 0.6),
        ("b22", "the evolved solver is a quarter point better.", 0.6),
        ("b23", "And the best idea was one the engine threw away, worth up to zero point three one.", 0.3),
    ], 1.0),
    ("close", 0.6, [
        ("b24", "MendelEvolve. Evolve ideas, not programs.", 0.3),
        ("b25", "Everything is public.", 0.2),
    ], 2.6),
]
