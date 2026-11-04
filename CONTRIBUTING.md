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

The same goes for PDFs attached to a source: only openly licensed ones are shared. A book you may not pass on can still be cited (title, author, pages); Bothy leaves the PDF itself out.

## 3. Send it

The easy way, no git needed:

1. On your Bothy, in edit mode, tap **Share**. Choose the guide, its shelf, or all of My guides, and give it a name. Bothy makes the file and leaves out pictures that can't be shared.
2. Scan the first QR code with your phone (or find the file in the Files app), then open the second one: the **Share guides** form here on GitHub.
3. Attach the file, say a sentence about it and its sources, tick the two boxes, and submit.

A robot checks the file within a few minutes and answers on the form. If something needs fixing, fix it in Bothy, share again, and edit the form with the new file; it checks again. If all is well, it opens a pull request and a maintainer reviews it. Sending an updated version of a pack that's already here works the same way; the robot raises its version.

The git way: unzip the file (one folder, named after the pack), copy that folder into `packs/knowledge/` in your fork, raise `version` in `pack.json` if the pack is already here, and open a pull request.

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
