# Campaign config for the sample videos

The four clips in this folder were generated and verified against this exact brief and master
prompt. Paste both into a new campaign as-is to get the verdicts listed in this folder's
[README](README.md); a different brief will score relevance differently and the verdicts won't
match.

**Brief**
```
Creator beauty videos for the Ora Velvet Collection launch: get-ready-with-me, tutorials, and
reviews where the creator applies, wears, or talks about the Ora Velvet Matte Lipstick, Velvet
Precision Eyeliner, or Velvet Glow Serum on camera. On-brief means one of these products is named
or clearly shown and used, even briefly. Off-brief is content where none of these products appear
or are mentioned, such as lifestyle, cooking, or unrelated clickbait.
```

**Master prompt**
```
This is the Ora Velvet Collection launch, a paid beauty ad campaign by Ora Cosmetics, a global
makeup brand. The campaign covers three products: the Velvet Matte Lipstick, the Velvet Precision
Eyeliner, and the Velvet Glow Serum.

ON-BRIEF: the creator applies, wears, or talks about one of these three products on camera, even
in a short clip. A quick application, a passing mention by name, or a product held up to the
camera all count as on-brief. It does NOT need to be a full step-by-step tutorial. OFF-BRIEF: none
of the three products appear or are mentioned at all, such as lifestyle, cooking, gaming, or
clickbait content with no product focus.

Review the whole clip across what is shown, spoken, and written on screen. Catch even brief,
single-frame on-screen text. Severity guidance for this campaign:
- Medical or treatment claims: any "clinically proven", "dermatologist tested to treat", or
  "clears / treats / cures / heals acne, eczema, rosacea or any condition", spoken or on screen,
  is HIGH severity.
- Unsafe product use: application near the eyes, near the inner waterline, or on broken skin is
  HIGH severity.
- Profanity: one mild or passing word is LOW severity; heavy or repeated explicit language is
  HIGH severity.
- Hate, harassment, drugs, or illegal behavior at any clear occurrence is HIGH severity.

Ground every finding in something actually seen, heard, or read in the video, with the exact
seconds. Do not invent violations.
```

Everything else (policy toggles, profanity tolerance, relevance threshold) can stay at the
defaults, all five policies enabled, "Balanced" profanity tolerance, 0.55 relevance threshold.
