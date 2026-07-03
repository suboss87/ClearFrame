# Sample videos

Four short clips, one per verdict, so you can upload a real video and confirm the pipeline lands
where it should, instead of only reading the mock fixtures or the one captured run in
[`docs/real_run_example.json`](../real_run_example.json).

Drop the files in here with these exact names, referenced from the main README:

| File | Expected verdict | Why |
|---|---|---|
| `oraad123a.mp4` | APPROVE | On-brief, clean across every policy |
| `ad345c.mp4` | REVIEW | Mild profanity, below the block threshold |
| `ad234b.mp4` | BLOCK | Unsafe product usage and a medical claim, both high severity |
| `ad456ob.mp4` | BLOCK | Off-brief, relevance gate, no campaign product shown |

Upload any of them through the UI creatiing new campaign (Settings → save a TwelveLabs key first) or drop them in a
linked bucket, and check the verdict and evidence against the table above.
