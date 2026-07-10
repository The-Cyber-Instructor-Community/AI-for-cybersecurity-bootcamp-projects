import os
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OllamaEmbeddings
from langchain_chroma import Chroma

def build_vector_db():
    print("Step 1: Loading compliance PDFs from ./data...")
    if not os.listdir("./data"):
        print("Error: Your ./data folder is empty. Drop a compliance PDF in there first!")
        return

    loader = PyPDFDirectoryLoader("./data")
    raw_documents = loader.load()
    print(f"Loaded {len(raw_documents)} pages from PDFs.")

    print("\nStep 2: Chunking document text into overlapping segments...")
    # Chunk size of 1000 characters with a 200 character overlap ensures 
    # sentences aren't cut off awkwardly between chunks.
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    documents = text_splitter.split_documents(raw_documents)
    print(f"Created {len(documents)} distinct text chunks.")

    print("\nStep 3: Generating local embeddings and saving to ChromaDB...")
    # We use the exact same local model weights to create vectors
    embedding_engine = OllamaEmbeddings(model="nomic-embed-text")
    
    # Initialize and persist the database locally
    vectordb = Chroma.from_documents(
        documents=documents,
        embedding=embedding_engine,
        persist_directory="./chroma_db"
    )
    print("Success! Your local compliance knowledge base is built and saved to ./chroma_db.")

if __name__ == "__main__":
    build_vector_db()