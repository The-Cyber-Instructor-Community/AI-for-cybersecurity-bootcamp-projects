from langchain_community.llms import Ollama
from langchain_chroma import Chroma
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.chains import create_retrieval_chain

def get_audit_chain():
    # 1. Load the existing local vector database
    embedding_engine = OllamaEmbeddings(model="nomic-embed-text")
    vectordb = Chroma(persist_directory="./chroma_db", embedding_function=embedding_engine)
    
    # Configure retriever to fetch relevant documentation sections
    retriever = vectordb.as_retriever(search_kwargs={"k": 3})

    # 2. Instantiate the local LLM with 0 temperature for factual rigidity
    llm = Ollama(model="llama3:8b", temperature=0.0)

    # 3. Design a specialized system prompt for GRC auditing using ChatPromptTemplate
    system_prompt = """You are a rigorous, expert Governance, Risk, and Compliance (GRC) Cybersecurity Auditor. 
Your objective is to evaluate internal corporate artifacts against official compliance framework requirements.

FRAMEWORK REQUIREMENT CONTEXT:
{context}

USER SUBMITTED INTERNAL ARTIFACT:
{input}

CRITICAL INSTRUCTIONS:
- Base your analysis strictly on the provided Framework Requirement Context.
- If the internal artifact does not fully address or fulfill a requirement mentioned in the context, flag it as a GAP.
- Do not make assumptions or hallucinate missing details. If a control is not explicitly written in the artifact, it does not exist.

Please output your findings in a clean, professional markdown format using the following structure:
# GRC AUDIT REPORT

### 1. SUMMARY ASSESSMENT
[Provide a high-level overview of the compliance health of the submitted artifact]

### 2. GAP ANALYSIS & DEFICIENCIES
[Identify every specific area where the artifact fails or falls short. Cite the specific framework rules from the context if possible]

### 3. RISK RATING & IMPACT
- **Assigned Risk Level:** [HIGH / MEDIUM / LOW]
- **Justification:** [Why this risk level? What happens if an attacker exploits this deficiency?]

### 4. ACTIONABLE REMEDIATION PLAN
[Provide direct, step-by-step engineering or operational instructions to update the artifact and remediate the identified gaps]
"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
    ])

    # 4. Assemble the modern retrieval chain
    # Create the document combining chain first
    question_answer_chain = create_stuff_documents_chain(llm, prompt)
    
    # Create the final retrieval chain combining retriever + document chain
    retrieval_chain = create_retrieval_chain(retriever, question_answer_chain)
    
    return retrieval_chain