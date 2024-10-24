# scholar2sql

scholar2sql streamlines literature reviews by automatically extracting structured data from scientific papers and storing it in a SQL database. Overall, this package offers two key advantages: (1) automated literature review processing (parsing, extraction, and structured organization of key information) and (2) proposed literature screening through customizable input parameters targeting your personal literature research outcomes.

This tool was used for the creation of the sql table of the drug screening literature review on ion channel found [here on channelpedia](https://channelpedia.epfl.ch/drug_mapping). The configuration file is located in the <i>examples</i> folder of this repository.

<figure markdown>
<IMG src="images/literature_search.drawio.svg"  alt="literature search" style="width:100%"/>
<br/><br/>
<figcaption>
Scholar2Sql mimics human expert literature review, extracting key features from articles, but scales the process to analyze a vastly larger number of publications than possible manually.
</figcaption>
</figure>
</details>

## Concepts

### 1- Large scientific article database of <u>All Open Access articles</u>:

<details open>
<summary>collapse</summary>
<figure markdown>
<IMG src="images/pdf_extractor.drawio.svg"  alt="Manual literature search" style="width:70%"/>
<br/><br/>
<figcaption>

The process of getting the Open-Access article: 1) first get the full-text from pubmed central 2) download the abstract 3) download the pdf and 4) parse it using GROBID.
</figcaption>
</figure>
</details>
<br/>

### 2- Extraction of features with <u>citations/sources</u>:

<details open>
<summary>collapse</summary>
<figure markdown>
<IMG src="images/literature_with_srouces.drawio.svg"  alt="Manual literature search" style="width:100%"/>
<br/><br/>
<figcaption>

Scholar2sql extracts features from text with sources by: 1) using a [RAG](https://aws.amazon.com/what-is/retrieval-augmented-generation) architecture. (the best sections are found using a [bm25](https://www.luigisbox.com/search-glossary/bm25/#:~:text=BM25%2C%20or%20Best%20Match%2025,based%20on%20their%20relevance%20scores) algorithm.) 2) Engineering the prompt by combining the best sections to a template (determined by the output features) and the examples (helping the model behavior). Finally ChatGPT fills the template using the informations from the sections with the help of the examples.</figcaption>
</figure>
</details>
<br/>


### 3- <u>Screening</u> literature review:

<details open>
<summary>collapse</summary>
<figure markdown>
<IMG src="images/screning_review.drawio.svg"  alt="Manual literature search" style="width:80%"/>
<br/><br/>
<figcaption>

Once you have defined your research question along with the input parameters, scholar2sql will loop over them and for each will find the most relevant articles try to download its content ([figure 2](#1--extraction-of-features-with-citationssources)) extract the features ([figure 3](#2--all-open-access-articles)) and fill the sql table.
</figcaption>
</figure>
</details>
<br/>

## Why this approach

Automated literature screening with large language models (LLMs) offers significant advantages for navigating the intricate world of scientific literature:
<br/><br/>
### 1- Making LLM Insights More Accessible

Researchers are finding new ways to use large language models (LLMs) to help process and analyze information. Our project aims to make the insights from these LLMs more widely available by organizing them in an easy-to-understand format. This could help people from various backgrounds access and use this information. Rather than having to repeatedly ask LLMs questions, which can be time-consuming and costly, our approach offers a way to access pre-organized information. We hope this might make research more efficient and accessible for more people.
<br/><br/>
### 2- Analyzing and Validating Scientific Literature

The sheer volume of scientific publications can be overwhelming, making manual reviews impractical. Our approach aims to create a tool that not only processes large datasets swiftly but also facilitates the comparison of scientific results. This helps in distinguishing truth from falsehood, filtering out irrelevant information, and pinpointing inconsistencies and errors in the literature, thereby highlighting critical areas for further investigation.
<br/><br/>

## Installation

```
git clone https://github.com/journeadrien/scholar2sql.git
pip install .
```

## Usage

1. Create a YAML configuration file, many fields are required (see Configuration section for details). This is a long process; take your time! There are examples provided in the 'examples' folder.
2. To enable pdf parsing, start a grobid service (I recommend using [docker here](https://grobid.readthedocs.io/en/latest/Grobid-docker/))
3. Try loading the config file and resolve the validation errors (if they occur)

```bash
s2s_load_settings path_to_config.yaml # s2s_load_settings examples/ic_drug.yaml
```
4. reset sql table
```bash
s2s_reset_sql_table path_to_config.yaml # s2s_reset_sql_table examples/ic_drug.yaml
```
5. run
```bash
s2s_run path_to_config.yaml # s2s_run examples/ic_drug.yaml
```
## Configuration

The package requires a YAML configuration file which specifies various settings. Below are explanations of each section in the configuration file:

### SQL Database Configuration

| Field    | Description                                     | Required |
|----------|-------------------------------------------------|----------|
| host     | Database host (use "localhost" for local)       | Yes      |
| username | Database username                               | Yes      |
| password | Database password                               | Yes      |
| database | Name of the database                            | Yes      |
| table    | Name of the table                               | Yes      |

#### Metadata Configuration

| Field    | Description                                                  |  Default                           |
|----------|--------------------------------------------------------------|-------------------------------------|
| to_save  | Metadata to add to sql (["pubmed_id", "format", "sections"]) | ["pubmed_id", "format", "sections"] |

### Logging Configuration

| Field             | Description                         | Options                  | Default |
|-------------------|-------------------------------------|--------------------------|---------|
| level             | Logging level for the main package  | debug, info, warn, error | info    |
| external_packages | Logging level for external packages | debug, info, warn, error | error   |

### Scholar Search Configuration

| Field                    | Description                                             | Required | Default |
|--------------------------|---------------------------------------------------------|----------|---------|
| top_sections_per_article | Number of top sections to select per article using BM25 | No       | 5       |
| email                    | Email for PubMed and Unpaywall API                      | Yes      |         |

#### PubMed Configuration

| Field                      | Description                                        | Required | Default      |
|----------------------------|----------------------------------------------------|----------|--------------|
| top_articles_per_search   | Number of top articles to select per PubMed search | No       | 10           |
| api_key                    | PubMed API key                                     | No       | ""           |
| additional_search_keywords | Additional keywords to include in PubMed search    | No       | ""           |
| tmp_pmc_folder             | Folder to store PubMed Central XML files           | No       | tmp/pmc      |
| tmp_abstract_folder        | Folder to store abstracts from PubMed              | No       | tmp/abstract |

#### GROBID Configuration

| Field          | Description                                | Required | Default |
|----------------|--------------------------------------------|----------|---------|
| url            | URL of the GROBID service                  | Yes      |         |
| tmp_pdf_folder | Folder to store downloaded PDF files       | No       | tmp/pdf |
| tmp_tei_folder | Folder to store TEI files (GROBID format)  | No       | tmp/tei |

### OpenAI Configuration

| Field       | Description                               | Required | Default    |
|-------------|-------------------------------------------|----------|------------|
| token       | OpenAI API key                            | Yes      |            |
| model       | Name of the OpenAI model to use           | No       | gpt-o-mini |
| temperature | OpenAI API key                            | No       | 0.         |
| verbose     | Whether to display full prompts           | No       | False      |

### Data Processing Configuration

| Field               | Description                                           | Required | Default |
|---------------------|-------------------------------------------------------|----------|---------|
| overwrite_existing  | Whether to overwrite existing records in the database | No       | False   |

### Prompt Configuration

This section defines the research goal, questions, input parameters, and output features for the literature review.

#### Research Goal and Question

| Field                    | Description                                              | Required | Default |
|--------------------------|----------------------------------------------------------|----------|---------|
| research_goal            | Overall goal of the literature search review             | Yes      |         |
| information_to_exclude   | Information to be excluded from the analysis             | No       | ""      |
| research_question        | Specific question to be answered (use {} for variables)  | Yes      |         |

#### Input Parameters

Define the input parameters of interest (e.g., drugs, proteins, compounds). You can have multiple inputs.

| Field       | Description                                   | Required | Default |
|-------------|-----------------------------------------------|----------|---------|
| name        | Name of the input parameter                   | Yes      |         |
| description | Description of the input parameter            | No       | ""      |
| max_length  | Maximum length of the input value             | Yes      |         |
| value       | List of possible values for the parameter     | Yes      |         |

For each value:

| Field        | Description                                             | Required | Default |
|--------------|---------------------------------------------------------|----------|---------|
| name         | Main name of the value                                  | Yes      |         |
| pubmed_alias | Aliases to be used in PubMed search (JSON list format)  | No       | ""      |
| llm_aliases  | Aliases to be used for LLM extraction (JSON list format)| No       | ""      |

#### Output Features

Define the features you want to extract from the literature.

| Field            | Description                                       | Required | Default |
|------------------|---------------------------------------------------|----------|---------|
| name             | Name of the output feature                        | Yes      |         |
| description      | Description of the output feature                 | No       | ""      |
| data_type        | Data type of the feature (e.g., str, int, dict)   | Yes      |         |
| required         | Whether the field is required in the LLM output   | No       | True    |
| multiple_values  | Whether the feature expects a list of values      | No       | False   |
| max_length       | Maximum length of the feature value (for strings) | Yes      |         |
| allowed_values   | List of allowed values (if applicable)            | No       | None    |

For allowed values:

| Field       | Description                           | Required | Default |
|-------------|---------------------------------------|----------|---------|
| name        | Name of the allowed value             | Yes      |         |
| alias       | Alias to be used by the LLM           | No       | ""      |
| description | Description of the allowed value      | No       | ""      |

#### Examples

Provide examples to guide the LLM's behavior. Each example should include:

- input_parameters
- sections (mock article content)
- output_features (expected output)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
