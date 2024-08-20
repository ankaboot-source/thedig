<a href="https://codeclimate.com/repos/6318a2c7c3233c21f30005a8/maintainability"><img src="https://api.codeclimate.com/v1/badges/18313db5cb56fa2c54e6/maintainability" /></a>
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](http://www.gnu.org/licenses/agpl-3.0)
[![Make the Web Open Again](https://img.shields.io/badge/%23MakeTheWebOpenAgain-indigo)](https://www.scientificamerican.com/article/long-live-the-web/)

# 🪨➜💎 TheDig API

Enrich data about someone (e.g job title, company, profile pictures etc.) using determinist, OSINT (Opensource Intelligence) and IA (future). Privacy-friendly design: only public data the mined person consent to share (no databreach) are exposed and any one could easily #OptOut.

## ✨ Features

### Person
Marketing-related data fetched from an email address and full name:
- Given name, Family name
- Job title
- Social Network's URL and LinkedIn's URL
- Profile pictures
- Company's name
- Work's location

If a person add #OptOut to his social profile bio, he won't be mined.

### Company
Company informations based solely on the domain:
- name
- website's url
- alternate name
- industry
- legal name
- description
- employees number
- founding date
- founders
- email
- telephone
- social network's URL

## 🛡️ Privacy-by-design

This program intend to be actively GDPR compliant and respectful of mined person's privacy. Our intent is to help user's enrich data on existing contacts not to spy nor gather data on someone with a malicious purpose.

We implemented proactively a few GDPR principles in the code itself:
- Right to Opt-Out: if the person mined use the tag #OptOut in its social profile, no enrichment will occur.
- Lawfulness, fairness and transparency: our sources of data are only public data the person already consent to share publicly. We do not mine databreached data nor doxing for examples. 
- Purpose and Accuracy: we rather prefer not to enrich with dubious information than take the risk of false positives, for examples the social profiles found are, as possible, checked to be the ones about the person itself. We do not mine social networks or websites that are irrelevant to marketing purposes.

By using this application, you must abid to local, international and ethical privacy rules. For instance, it's highly recommended to inform the person's enriched that he has been the object of this mining. Such feature is not in the scope of this present OpenSource repository. Please reach contact@ankaboot.fr for further enquiries.

## 🏗️ How to use

### Configure
To run this project, you'll need a few environement variables which includes some API keys from Google. Please edit [default.env](default.env) and rename it as `.env`.

You'll need a few API keys, depending on which search engine you wish to use, yet Google Vision (reverse-image search) is mandatory. Have a look at [default.env] for instructions on how to create them.

In order to help you start smoothly, we provided a script for Google `setup_googlecloud.sh`. Run it to set-up automatically Google Vision API. By default, the project will be `thedig` and so the API key. If you wish to change defaults, feel free to modify the script by yourself.

### Launch

Download it and:
```bash
  docker-compose up -d
```

## 🤝 How to contribute
You're welcome! First, have a look on issues open and closed. If nothing is related to your needs, either open an issue or [fork, create a branch and submit your PR](https://docs.github.com/en/get-started/quickstart/contributing-to-projects).
### Launch in developer mode
- Set the `LOG_LEVEL` to `DEBUG` in `.env`
- Enter the ``thedig`` folder and run it this way : ``uvicorn main:app --reload``
### Contributor Copyright Agreement
In consideration of your contributions to this product, you shall be granted the right to utilize, modify, and disseminate the product in conjunction with your contributions. Simultaneously, you hereby grant the software editor (Ankaboot Company) an irrevocable, perpetual, and unrestricted license to employ, adapt, and publish, including for commercial purposes, your contributions, in their entirety.

## ⚠️ Support

For support, contact by email contact@ankaboot.io for commercial support or open an issue for community support (no-SLA, no-Warranty).


## 📃 License

This software is a free software (open source) [dual-licensed](DUAL-LICENSE) under the [AGPL](LICENSE) (No SLA, No Warranty) and a [commercial license](DUAL-LICENSE). Basically, that means that you could use, modify and distribute this software freely if the derivative work is OpenSource itself (OSI-approved). For axemple, if your software is a Software-as-a-Service, your SaaS must be OpenSource itself. If you wish to use this software in a non-OSI approved license, aka proprietary software, you must buy a commercial license from the editor of this product (aka ankaboot.io - contact@ankaboot.io).
