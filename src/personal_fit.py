import yaml
import os
from src.config import PROFILE_PATH
from src.database import get_connection

def load_profile():
    if not os.path.exists(PROFILE_PATH):
        return {}
    with open(PROFILE_PATH, 'r') as f:
        return yaml.safe_load(f) or {}

def calculate_overlap(text_fields, target_list):
    if not target_list or not text_fields:
        return 0, []
        
    text = " ".join([str(t) for t in text_fields if t]).lower()
    matches = []
    
    for item in target_list:
        if item.lower() in text:
            matches.append(item)
            
    score = (len(matches) / len(target_list)) * 100 if target_list else 0
    # Cap score at 100 but allow fewer matches to give a decent score
    score = min(100.0, len(matches) * 20.0) 
    return score, matches

def score_opportunity(title, description, technologies):
    profile = load_profile()
    
    skills = profile.get('skills', [])
    interests = profile.get('interests', [])
    languages = profile.get('preferred_languages', [])
    learning_targets = profile.get('learning_targets', [])
    
    text_fields = [title, description, technologies]
    
    skill_score, skill_matches = calculate_overlap(text_fields, skills)
    interest_score, interest_matches = calculate_overlap(text_fields, interests)
    lang_score, lang_matches = calculate_overlap(text_fields, languages)
    learning_score, learning_matches = calculate_overlap(text_fields, learning_targets)
    
    # 40% skills/languages, 40% interests, 20% learning
    base_tech = (skill_score + lang_score) / 2
    personal_fit = (base_tech * 0.4) + (interest_score * 0.4) + (learning_score * 0.2)
    
    missing_skills = [s for s in skills if s not in skill_matches][:3] # just a sample
    
    return {
        'score': round(personal_fit, 2),
        'matched_skills': skill_matches + lang_matches,
        'matched_interests': interest_matches,
        'learning_value': learning_matches,
        'missing_skills': missing_skills,
        'why_it_fits': f"Matches {len(skill_matches)} skills and {len(interest_matches)} interests."
    }

def get_ranked_opportunities(verified_only=False, confidence_filter=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # We fetch GSoC Projects
        cursor.execute('''
        SELECT p.id, p.org_slug, p.title, p.description, p.technologies, o.opportunity_score, o.name, o.is_verified_github, o.opportunity_confidence, p.classified_tags
        FROM gsoc_projects p
        JOIN organizations o ON p.org_slug = o.slug
        ''')
        projects = cursor.fetchall()
        
        profile = load_profile()
        priorities = profile.get('priorities', {})
        
        results = []
        for p in projects:
            p_id, org_slug, title, desc, techs, org_score, org_name, is_verified, conf, tags = p
            org_score = org_score or 0.0
            is_verified = bool(is_verified)
            conf = conf or "LOW"
            
            if verified_only and not is_verified:
                continue
                
            if confidence_filter and conf.upper() != confidence_filter.upper():
                continue
            
            fit = score_opportunity(title, desc, techs)
            
            priority_bonus = 0
            priority = priorities.get(org_slug)
            if priority == 'A+': priority_bonus = 15
            elif priority == 'A': priority_bonus = 10
            elif priority == 'B': priority_bonus = 5
            
            final_score = (fit['score'] * 0.3) + (org_score * 0.7) + priority_bonus
            
            # Penalize final score if not verified
            if not is_verified:
                final_score = final_score * 0.5
                
            final_score = min(100.0, final_score)
            
            completeness = "historical-only"
            if is_verified:
                completeness = "verified" if conf == "HIGH" else "partial"
            
            if final_score > 5:
                results.append({
                    'id': f"proj-{p_id}",
                    'type': 'GSoC Project',
                    'organization': org_name,
                    'title': title,
                    'technology': techs,
                    'personal_fit': fit['score'],
                    'org_score': org_score,
                    'final_score': round(final_score, 2),
                    'why_it_fits': fit['why_it_fits'],
                    'missing_skills': fit['missing_skills'],
                    'matched_skills': fit['matched_skills'],
                    'matched_interests': fit['matched_interests'],
                    'learning_value': fit['learning_value'],
                    'data_completeness': completeness,
                    'confidence': conf,
                    'tags': tags
                })
        
        results.sort(key=lambda x: x['final_score'], reverse=True)
        return results
