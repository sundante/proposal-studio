# Using your own PowerPoint template

`/render` writes the deck onto **your** template with python-pptx; no model is involved. You map
each slide type to one of the template's layouts once, in `config/layout_map.yaml`.

1. Put the template in `templates/` (`.pptx` or `.potx`; that folder is gitignored, apart from
   `templates/sample/`).
2. Inspect it:

   ```bash
   studio template inspect templates/firm.potx
   ```

   This prints each layout with its content placeholders, for example
   `[4] Comparison: 0=TITLE, 1=BODY, 2=OBJECT, 3=BODY, 4=OBJECT`, and writes
   `templates/firm.layouts.json` with the sizes.
3. Edit `config/layout_map.yaml`:

   ```yaml
   template: templates/firm.potx
   remove_existing_slides: true      # drop the template's example slides
   layouts:
     understanding: { layout: "Title and Content", placeholders: { title: 0, bullets: 1 } }
     before_after:
       layout: "Comparison"
       placeholders: { title: 0, before_title: 1, before: 2, after_title: 3, after: 4 }
     solution_architecture:
       layout: "Title Only"
       placeholders: { title: 0 }
       diagram_area: { left: 0.5, top: 1.6, width: 12.3, height: 5.3 }   # inches
     why_us: { layout: "Title and Content", placeholders: { title: 0, bullets: 1 }, limits: { bullet: 90 } }
   ```

   Placeholders can be given by `idx` (a number) or by name. The fields are `title`,
   `subtitle`, `bullets`, `before_title`, `before`, `after_title`, `after`, `stages` and `steps`.
   Architecture layers are drawn as boxes inside `diagram_area`.
4. Render the sample deck to check the mapping:
   `studio render --deck tests/fixtures/sample_deck.json --out build/`.

**What the renderer does:**
- Text over a limit is cut at a word boundary with "…", and extra bullets are dropped.
- Placeholders left unfilled are removed, so no "Click to add text" boxes are left.
- Sources go into the speaker notes.
- Output is versioned (`<opp>-vN.pptx`) and never overwritten.

The QA report lists anything truncated, any empty placeholders, slides without sources, and the
writer's review flags. A slide type with no mapping, or a layout name the template doesn't have,
is a QA error, and the message lists the template's layouts.

`.potx` files work as they are: they're read through an in-memory copy, and the file itself is
never changed.
