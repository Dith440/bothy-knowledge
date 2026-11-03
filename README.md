# Bothy community knowledge

Guides and medical protocols for [Bothy](https://github.com/Dith440/bothy) decks, written and reviewed by the people who use them. Everything here can be shared: texts and pictures are under open licences, mostly CC BY-SA 4.0.

> **Status: not public yet.** This collection starts with one example guide.

## Getting packs onto a deck

On the deck, open **Knowledge**, tap the pencil, then **Import**. Packs from this collection are listed under *Community collection*; install or update them there. Or in a terminal:

```sh
bothy content knowledge list                 # what's in the collection, and what's installed
sudo bothy content knowledge add bothy-starter
sudo bothy content knowledge update          # install newer versions of installed packs
```

Installed community packs are read-only, so updates can replace them safely. To change one for yourself, make an editable copy in the editor.

## What's here

```
packs/knowledge/<pack-id>/    Knowledge guides, one folder per pack
packs/medical/<pack-id>/      Medical protocols (stricter review)
tools/check.py                the checks every contribution must pass
tools/build.py                builds the pack files and catalogue.json that decks download
```

A pack is a folder of plain files, one Markdown file per guide and language, so changes read well in a pull request. The format is described in Bothy's [docs/knowledge-packs.md](https://github.com/Dith440/bothy/blob/main/docs/knowledge-packs.md).

The catalogue and pack files are published at `https://dith440.github.io/bothy-knowledge/` after every change on `main`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: write on your deck, export the pack as **Shareable**, and open a pull request with its folder.

## Licence

Texts and pictures are licensed under [CC BY-SA 4.0](LICENSE) unless a picture's `.json` file says otherwise (CC BY 4.0, CC0 and public domain are also accepted). The tools in `tools/` are GPL-3.0, like Bothy.
