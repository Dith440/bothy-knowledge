# Contributing guides and protocols

Thank you for sharing what you know. Every pack here ends up on decks people rely on when things go wrong, so the bar is simple: correct, clear, checkable, and free to share.

## 1. Write it on your deck

Open **Knowledge**, tap the pencil, and write in the editor. It has a built-in *How to write a guide*. The essentials:

- One task per guide; the title says what you do.
- Steps: one action each, with numbers, times and amounts.
- The warning names the one thing that can hurt someone.
- Name your sources (book and page, or a reliable website) in the source notes.
- Write both English and German. If you can only write one, say so in the pull request; someone else can translate.

## 2. Pictures

Only pictures you made yourself, or ones with an open licence (CC BY-SA 4.0, CC BY 4.0, CC0, public domain). Every picture needs its maker and where it comes from. Crops from books and anything marked non-commercial or no-derivatives can't be shared; the Shareable export leaves them out for you.

## 3. Export and send it

1. In the editor, choose **Export**, then **Shareable**, the pack, shelf or guide you want to share, and give the pack an id that's free in this collection.
2. Unzip the file. It holds one folder, named after the pack.
3. Copy that folder into `packs/knowledge/` (or `packs/medical/`) in your fork of this repo, and open a pull request.

To change a pack that's already here, change its files and raise its `version` in `pack.json` (1.0.0 → 1.0.1 for fixes, 1.1.0 for new guides).

## 4. Checks and review

GitHub runs `tools/check.py` on every pull request. You can run it yourself first:

```sh
pip install pillow
python3 tools/check.py
```

It checks the format, the licences, that every picture is real and safe, sizes (2 MB per picture, 50 MB per pack), that versions go up, and that no guide is in two packs on the same shelf.

Then a maintainer reads the content. We check that steps are safe and complete, that sources back them up, and that both languages say the same thing.

## Medical protocols

Medical packs are held to a higher standard:

- Every protocol must be reviewed by a qualified person (for example a doctor, paramedic or nurse), named in the protocol's review. The check enforces the name; maintainers check the qualification.
- A medical reviewer listed in `.github/CODEOWNERS` must approve the pull request.
- Follow a current, citable guideline, and cite it.
- No dosages for prescription drugs unless the guideline gives them for trained responders, and the protocol is marked for trained people only.

## Licence of your contribution

By opening a pull request you agree that your texts are published under CC BY-SA 4.0, and that you have the right to share every picture under the licence given in its `.json` file.
