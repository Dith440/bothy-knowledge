# Bothy community knowledge

Guides and medical protocols for [Bothy](https://github.com/Dith440/bothy) decks, written and reviewed by the people who use them. Everything here can be shared: texts and pictures are under open licences, mostly CC BY-SA 4.0.

> **Status: not public yet.** This collection starts with one example guide.

## Getting packs onto a deck

On the deck, open **Knowledge**, tap the pencil, then **Get guides**: install or update packs from this collection there. Or in a terminal:

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
tools/submission.py           the robot behind the Share guides form
```

A pack is a folder of plain files, one Markdown file per guide and language, so changes read well in a pull request. The format is described in Bothy's [docs/knowledge-packs.md](https://github.com/Dith440/bothy/blob/main/docs/knowledge-packs.md).

The catalogue and pack files are published at `https://dith440.github.io/bothy-knowledge/` after every change on `main`. The catalogue is signed (`catalogue.json.sig`, Ed25519) with the repository secret `CATALOGUE_SIGNING_KEY`; Bothy ships the matching public key and refuses a catalogue whose signature is missing or doesn't match, and the publish workflow stops rather than publish unsigned. A new key needs a Bothy release with the new public key (`CATALOGUE_KEY` in `services/knowledge-packs/bothy_pack_files.py`).

`packs/knowledge/bothy-community/` belongs to the community site (contribute.bothy.cloud): the guides its moderators accepted. The site keeps it current through pull requests from its `community-sync` branch and merges them when the checks pass; the checks make sure that branch changes nothing outside that folder. Don't edit the folder by hand, the site replaces it on its next change. When no guide is published on the site any more, the folder holds only `withdrawn.json`: the catalogue then lists the pack under `withdrawn`, and Bothys that installed it remove it with their next update. Any pack can be withdrawn the same way: replace its folder's contents with a `withdrawn.json` (`id`, `kind`, a higher `version`, the `withdrawn` date and a `reason`).

A pack that needs a newer Bothy names the oldest one in `pack.json` (`"minBothy": "0.2.0"`); older decks list it without installing it.

## Contributing

Write guides on your Bothy (Knowledge → pencil), tap **Share**, and attach the file it makes to the [Share guides form](../../issues/new?template=share-guides.yml). A robot checks it and prepares the addition; a maintainer reads it before it goes live. More in [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Texts and pictures are licensed under [CC BY-SA 4.0](LICENSE) unless a picture's `.json` file says otherwise (CC BY 4.0, CC0 and public domain are also accepted). The tools in `tools/` are GPL-3.0, like Bothy.
