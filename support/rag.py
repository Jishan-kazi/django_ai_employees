from pypdf import PdfReader
import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
import os

client = chromadb.PersistentClient(path="./chromadb")
embedding_fn = DefaultEmbeddingFunction()

collection = client.get_or_create_collection(
    name="coolbreeze_docs",
    embedding_function=embedding_fn
)





def make_chunks(text, chunk_size=500):
    words = text.split()

    all_chunks = []
    current_chunk = []
    current_chunk_size = 0
    
    for word in words:
        if current_chunk_size <= chunk_size:
            current_chunk.append(word)
            current_chunk_size += len(word) + 1
        else:
            all_chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_chunk_size = 0

    if current_chunk:
        all_chunks.append(" ".join(current_chunk))
        current_chunk = []

    return all_chunks


def load_documents():
    doc_path = 'support/documents'

    documents = []
    ids = []

    for filename in os.listdir(path=doc_path):
        if filename.endswith('.pdf'):
            filepath = os.path.join(doc_path, filename)

            reader = PdfReader(filepath)
            raw_text = ""
            for page in reader.pages:
                raw_text += page.extract_text()

            chunks = make_chunks(raw_text)

            for i, chunk in enumerate(chunks):
                documents.append(chunk)
                ids.append(f"{filename}_{i}")

    if documents:
        collection.add(
            ids=ids,
            documents=documents,
        )

    print(f"Loaded {len(documents)} chunks into chromadb")


def search_knowledge_base(query):
    results = collection.query(
        query_texts=[query],
        n_results=3
    )

    if not results['documents'][0]:
        return "No relevant information found in company documents"

    matched_chunk = results['documents'][0]
    return "\n\n".join(matched_chunk)

            

            


