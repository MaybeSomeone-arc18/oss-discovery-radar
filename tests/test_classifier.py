from src import classifier

def test_extract_tags():
    title = "Machine Learning AI System for Robotics"
    desc = "We use python and C++"
    tech = "ROS, opencl"
    
    tags = classifier.extract_tags([title, desc, tech])
    
    assert "AI" in tags
    assert "ML" in tags
    assert "robotics" in tags
    assert "Python" in tags
    assert "C++" in tags
    assert "GPU" in tags # opencl maps to GPU
    assert "web" not in tags
    
def test_extract_tags_boundaries():
    # 'main' contains 'ai' but shouldn't match AI
    tags = classifier.extract_tags(["The main package contains rustlang code"])
    assert "AI" not in tags
    assert "Rust" in tags
