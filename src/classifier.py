import json
from src.database import get_connection

TAG_KEYWORDS = {
    "AI": ["ai", "artificial intelligence", "agentic", "llm", "genai", "generative ai"],
    "ML": ["ml", "machine learning", "deep learning", "neural network", "transformer", "pytorch", "tensorflow"],
    "computer vision": ["computer vision", "opencv", "slam", "object detection", "image processing", "vision"],
    "robotics": ["robotics", "ros", "ros2", "robot", "gazebo", "drone"],
    "Rust": ["rust", "rustlang"],
    "C++": ["c++", "cpp", "c/c++"],
    "Python": ["python", "django", "flask", "fastapi"],
    "Java": ["java", "spring", "jvm", "kotlin"],
    "Android": ["android", "mobile", "app"],
    "systems": ["systems", "kernel", "os", "operating system", "linux", "compiler", "llvm", "gcc"],
    "networking": ["networking", "network", "tcp", "udp", "bgp", "sdn"],
    "security": ["security", "crypto", "encryption", "vulnerability", "auth", "owasp", "cve"],
    "developer tooling": ["developer tooling", "devtool", "cli", "debugger", "profiler", "sdk", "api"],
    "performance": ["performance", "optimization", "speedup", "latency", "throughput", "high performance"],
    "GPU": ["gpu", "cuda", "opencl", "vulkan", "opengl"],
    "distributed systems": ["distributed systems", "distributed", "consensus", "raft", "paxos", "kubernetes", "k8s", "cluster"],
    "web": ["web", "frontend", "backend", "react", "vue", "angular", "html", "css", "javascript", "typescript", "wasm", "webassembly"],
    "databases": ["databases", "database", "sql", "postgresql", "mysql", "nosql", "mongodb", "redis", "storage"]
}

def extract_tags(text_fields):
    text = " ".join([str(t) for t in text_fields if t]).lower()
    tags = set()
    for tag, keywords in TAG_KEYWORDS.items():
        for kw in keywords:
            # If the keyword contains non-word characters (like +), simple \b fails.
            if not kw.replace(' ', '').isalnum():
                if kw in text:
                    tags.add(tag)
                    break
            else:
                import re
                pattern = r'\b' + re.escape(kw) + r'\b'
                if re.search(pattern, text):
                    tags.add(tag)
                    break
    return list(tags)

def backfill_classifications():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, description, technologies FROM gsoc_projects")
        rows = cursor.fetchall()
        for row in rows:
            p_id, title, desc, techs = row
            tags = extract_tags([title, desc, techs])
            cursor.execute("UPDATE gsoc_projects SET classified_tags = ? WHERE id = ?", (json.dumps(tags), p_id))
        conn.commit()
