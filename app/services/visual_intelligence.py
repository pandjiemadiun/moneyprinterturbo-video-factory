"""
Visual Intelligence Module for MoneyprinterTurbo.

This module implements visual-intent extraction to improve stock footage
search relevance by converting abstract narration into concrete visual queries.

The approach:
1. Parse script sentences and identify key concepts
2. Map concepts to visualizable subjects/actions/locations
3. Generate multiple visual-first search terms per concept
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class VisualIntent:
    """Represents the visual components extracted from a narration."""
    subject: List[str] = field(default_factory=list)  # Who/what is the focus
    action: List[str] = field(default_factory=list)    # What are they doing
    object_list: List[str] = field(default_factory=list)  # What are they interacting with
    context: List[str] = field(default_factory=list)   # Where/setting
    mood: List[str] = field(default_factory=list)    # Emotional tone
    camera: List[str] = field(default_factory=list)  # Shot type (close-up, wide, etc.)


# Indonesian visual vocabulary mapping
# Maps abstract concepts to concrete visual representations
VISUAL_CONCEPTS_ID = {
    # Psychology/Emotion Concepts
    "mengabaikan": ["ignoring", "ignoring messages", "person ignoring phone"],
    "terpikirkan": ["thinking about", "reflection", "person thinking"],
    "kesepian": ["lonely", "isolated", "alone person", "lonely silhouette"],
    "status sosial": ["social status", "status anxiety", "status symbol"],
    "mengapa": ["why", "reason", "explanation", "person curious"],
    "ingatan": ["memory", "remembering", "past moment"],
    
    # Money/Business Concepts
    "mempersonalisasi": ["personalized", "customized", "personal touch"],
    "terlihat": ["looking", "appearing", "seems", "person presenting"],
    "mewah": ["luxury", "premium", "expensive", "luxury items"],
    "beli": ["buying", "purchase", "shop", "shopping"],
    "uang": ["money", "currency", "cash", "financial"],
    "berkebutuhan": ["need", "desire", "want", "craving"],
    "tabungan": ["saving", "saving money", "budget"],
    
    # Productivity Concepts
    "kebiasaan": ["habit", "routine", "daily habit", "person doing"],
    "mengapa": ["why", "reason", "because", "explanation"],
    "pemalas": ["lazy", "lazy person", "slothful"],
    "gangguan": ["distraction", "interruption", "stopped by"],
    "pagi": ["morning", "early morning", "dawn"],
    "bangun": ["waking up", "alarm clock", "wake up"],
    "bekerja": ["working", "office work", "at desk", "computer work"],
    "fokus": ["focus", "concentrating", "focused person"],
    "malas": ["lazy", "idler", "procrastination"],
}

# English visual vocabulary for search terms
ENGLISH_VISUAL_TERMS = {
    "lonely": "lonely person",
    "thinking": "person thinking",
    "phone call": "phone call missed",
    "messages": "text messages ignored",
    "social status": "social status anxiety",
    "suspicion": "suspecting person",
    "rejection": "rejected person",
    "memory": "memory thoughts",
    "uncertainty": "person uncertain",
    "curiosity": "curious person",
    
    "luxury": "luxury items",
    "shopping": "shopping mall",
    "expensive clothes": "expensive clothing",
    "rich appearance": "appear wealthy",
    "appearance": "luxury appearance",
    "hidden cost": "hidden costs",
    "credit card": "credit card spending",
    "bill": "paying bills",
    
    "habit": "morning habit",
    "alarm": "alarm clock",
    "snooze": "snooze button",
    "productivity": "productivity issues",
    "phone": "person on phone",
    "office": "office work",
    "desk": "desk work",
    "sleeping": "person sleeping",
    "stress": "stressful situation",
}

# Common stock footage search patterns
# Maps Indonesian concepts to English visual search terms that work well with stock providers
CONCEPT_TO_VISUAL_MAP = {
    # Indonesian -> English visual search terms
    "orang": ["person", "people", "human", "man", "woman", "individual"],
    "mengabaikan": ["ignoring", "disregarding", "overlooking", "person ignoring"],
    "berpikir": ["thinking", "reflection", "contemplation", "person thinking"],
    "telepon": ["phone", "mobile phone", "smartphone", "cell phone"],
    "pesan": ["message", "text message", "chat", "messaging"],
    "kesepian": ["lonely", "isolated", "solitary", "lonely person"],
    "sukses": ["successful", "wealthy", "luxury", "success"],
    "mewah": ["luxury", "premium", "expensive", "high-end"],
    "beli": ["buying", "shopping", "purchase", "customer"],
    "uang": ["money", "currency", "cash", "financial"],
    "rumah": ["house", "home", "residence", "building"],
    "kantor": ["office", "workplace", "business", "office building"],
    "pekerjaan": ["work", "job", "working", "employee"],
    "fokus": ["focus", "concentrating", "focused", "attention"],
    "gangguan": ["distraction", "interruption", "disturbed", "interrupted"],
    "pagi": ["morning", "sunrise", "early morning", "dawn"],
    "bangun": ["waking up", "alarm", "morning routine", "early riser"],
    "malas": ["lazy", "slothful", "slow", "inactive"],
    "kebiasaan": ["habit", "routine", "daily habit", "regular activity"],
    "tempat tidur": ["bed", "sleeping", "bedroom", "bedroom scene"],
    "alarm": ["alarm clock", "wake up", "morning alarm", "beep alarm"],
    "snooze": ["snooze button", "sleeping alarm", "alarm snooze"],
    "bekerja": ["working", "work", "on computer", "typing"],
    "laptop": ["laptop", "computer", "working on computer", "office computer"],
    "stress": ["stress", "anxiety", "worried", "concern"],
    "rencana": ["planning", "planning session", "strategy", "planning desk"],
    "ide": ["idea", "inspiration", "creative", "inspired"],
}

# Subject-action-object patterns for generating visual queries
VISUAL_PATTERNS = [
    "{subject} {action}",
    "{subject} {action} {object}",
    "{subject} in {context}",
    "{subject} looking {mood}",
    "{object} {action}",
    "{action} {subject}",
    "{subject} {mood}",
    "{subject} {context}",
]


def extract_visual_intent(text: str, language: str = "id") -> VisualIntent:
    """
    Extract visual intent components from Indonesian text.
    
    This function analyzes narration text and extracts the key visual elements
    that can be used to generate stock footage search queries.
    
    Args:
        text: The narration script or sentence to analyze
        language: "id" for Indonesian, "en" for English
        
    Returns:
        VisualIntent object containing extracted visual components
    """
    intent = VisualIntent()
    
    text_lower = text.lower()
    
    # Extract subjects (people, objects, concepts)
    subjects = _extract_subjects(text_lower, language)
    if subjects:
        intent.subject = subjects
    
    # Extract actions
    actions = _extract_actions(text_lower, language)
    if actions:
        intent.action = actions
    
    # Extract objects
    obj_list = _extract_objects(text_lower, language)
    if obj_list:
        intent.object_list = obj_list
    
    # Extract contexts/settings
    contexts = _extract_contexts(text_lower, language)
    if contexts:
        intent.context = contexts
    
    # Extract moods/emotions
    moods = _extract_moods(text_lower, language)
    if moods:
        intent.mood = moods
    
    return intent


def _extract_subjects(text: str, language: str) -> List[str]:
    """Extract potential subjects (people, objects, concepts) from text."""
    subjects = []
    
    # Common Indonesian subjects
    id_subjects = [
        "orang", "orang miskin", "orang kaya", "pekerja", "karyawan", 
        "pengusaha", "pelaku", "teman", "kawan", "suami", "istri",
        "laki-laki", "perempuan", "wanita", "pria", "anak", "bayi",
        "lansia", "penderita", "penghidup", "manusia", " individu",
        "person", "people", "man", "woman", "child", "human"
    ]
    
    for subj in id_subjects:
        if subj in text:
            if "_" in subj:
                subjects.append(subj.replace("_", " "))
            else:
                subjects.append(subj)
    
    # English subjects
    en_subjects = ["person", "people", "man", "woman", "child", "human", "individual"]
    for subj in en_subjects:
        if subj in text:
            subjects.append(subj)
    
    # Remove duplicates while preserving order
    seen = set()
    result = []
    for s in subjects:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            result.append(s)
    
    return result if subjects else ["person"]


def _extract_actions(text: str, language: str) -> List[str]:
    """Extract actions/verbs from text."""
    actions = []
    
    id_actions = [
        "mengabaikan", "melewatkan", "menghentikan", "menunda", "menunggu",
        "berpikir", "mengingat", "memikirkan", "mencari", "menyelidiki",
        "beli", "membeli", "membeli", "menabung", "menghemat",
        "bangun", "tidur", "bangun tidur", "menggunakan", "memakai",
        "menonton", "membuka", "menutup", "mengetik", "bekerja",
        "belajar", "main", "bermain", "jalan", "berlari", "berjalan",
        "memakai", "pakai", "susun", "susun rumah",
    ]
    
    for action in id_actions:
        if action in text:
            actions.append(action.replace("_", " "))
    
    # English actions
    en_actions = [
        "thinking", "ignoring", "buying", "shopping", "waking up",
        "working", "sleeping", "using", "opening", "closing",
        "typing", "studying", "walking", "running", "looking at"
    ]
    
    for action in en_actions:
        if action in text:
            actions.append(action)
    
    return list(set(actions))


def _extract_objects(text: str, language: str) -> List[str]:
    """Extract objects from text."""
    objects = []
    
    id_objects = [
        "telepon", "pons", "pons pintar", "pesan", "WA", "WhatsApp",
        "uang", "uang cash", "kartu kredit", "dompet", "uang tunai",
        "rumah", "apartemen", "kantor", "toko", "mall",
        "laptop", "komputer", "pons", "handphone",
        "jam", "alarm", "media sosial", "media",
        "baju", "pakaian", "lokal", " mahal", "mewah",
    ]
    
    for obj in id_objects:
        if obj in text:
            objects.append(obj.replace("_", " "))
    
    # English objects
    en_objects = [
        "phone", "phone call", "message", "text message", "smartphone",
        "money", "cash", "credit card", "wallet",
        "house", "apartment", "office", "store", "mall",
        "laptop", "computer", "phone", "mobile phone",
        "alarm", "social media", "clothing", "expensive item", "luxury"
    ]
    
    for obj in en_objects:
        if obj in text:
            objects.append(obj)
    
    return list(set(objects))


def _extract_contexts(text: str, language: str) -> List[str]:
    """Extract contexts/settings from text."""
    contexts = []
    
    id_contexts = [
        "kantor", "ruang kerja", "tempat kerja", "gedung", "gedung perkantoran",
        "mall", "toko", "sekolah", "uni", "universitas",
        "rumah", "apartemen", "condominium", "apartemen mewah",
        "kota", "kota besar", "skyline", "jalan", "jalan tol",
    ]
    
    for ctx in id_contexts:
        if ctx in text:
            contexts.append(ctx.replace("_", " "))
    
    return list(set(contexts))


def _extract_moods(text: str, language: str) -> List[str]:
    """Extract moods/emotions from text."""
    moods = []
    
    id_moods = [
        "sedih", "marah", "gesep", "cemas", "takut",
        "senang", "bahagia", "senang", "gembira", "terhibur",
        "stress", "tekanan", "beban", "lelah", "mual",
    ]
    
    for mood in id_moods:
        if mood in text:
            moods.append(mood)
    
    en_moods = ["lonely", "sad", "angry", "anxious", "stressed", "happy", "busy"]
    for mood in en_moods:
        if mood in text:
            moods.append(mood)
    
    return list(set(moods))


def generate_visual_queries_from_text(
    text: str, 
    language: str = "id",
    max_queries: int = 5
) -> List[str]:
    """
    Generate visual-first search queries from narration text.
    
    This is the main entry point for the visual intelligence enhancement.
    It extracts visual components from text and generates concrete, visual
    search queries suitable for stock footage APIs.
    
    Args:
        text: The narration script or sentence
        language: "id" for Indonesian, "en" for English
        max_queries: Maximum number of queries to generate
        
    Returns:
        List of visual-first search queries
    """
    intent = extract_visual_intent(text, language)
    
    queries = []
    
    # Generate queries using visual patterns
    for pattern in VISUAL_PATTERNS:
        # Fill in the pattern template with extracted components
        query = pattern.format(
            subject=intent.subject[0] if intent.subject else "person",
            action=intent.action[0] if intent.action else "working",
            object=intent.object_list[0] if intent.object_list else "items",
            context=intent.context[0] if intent.context else "office",
            mood=intent.mood[0] if intent.mood else "focused"
        )
        
        # Normalize to English for better stock footage compatibility
        query = _normalize_to_english_visual(query, text)
        
        if query and query not in queries:
            queries.append(query)
        
        if len(queries) >= max_queries:
            break
    
    # Also try direct concept mapping
    direct_queries = _get_direct_visual_queries(text, language)
    for q in direct_queries[:max_queries - len(queries)]:
        if q not in queries:
            queries.append(q)
    
    return queries[:max_queries]


def _normalize_to_english_visual(indonesian_like: str, original_text: str) -> str:
    """Convert Indonesian-like terms to English visual search terms."""
    result = indonesian_like.lower()
    
    # Map common Indonesian terms to English visual terms
    for indo_term, english_terms in CONCEPT_TO_VISUAL_MAP.items():
        if indo_term in result:
            # Replace with English visual terms
            for eng_term in english_terms:
                result = result.replace(indo_term, eng_term)
    
    # Clean up and normalize
    result = re.sub(r'\s+', ' ', result).strip()
    
    # If result is still mostly Indonesian, return a safe English fallback
    if result == indonesian_like.lower():
        # Try to extract visual meaning
        for key, visual_terms in ENGLISH_VISUAL_TERMS.items():
            if key in original_text.lower():
                return visual_terms
    
    return result


def _get_direct_visual_queries(text: str, language: str) -> List[str]:
    """Get direct visual queries by mapping text to known visual concepts."""
    queries = []
    text_lower = text.lower()
    
    for concept, visual_terms in CONCEPT_TO_VISUAL_MAP.items():
        if concept in text_lower:
            for term in visual_terms:
                if term.lower() not in [q.lower() for q in queries]:
                    queries.append(term)
                    if len(queries) >= 3:
                        break
        if len(queries) >= 3:
            break
    
    return queries


def enhance_search_terms(
    original_terms: List[str],
    video_script: str,
    language: str = "id",
    enhancement_factor: int = 2
) -> List[str]:
    """
    Enhance original search terms with visual-intent derived queries.
    
    This function combines the original LLM-generated terms with additional
    visual-first queries derived from the script content. The goal is to
    provide both concise and concrete search options to the stock providers.
    
    Args:
        original_terms: Terms from LLM (potentially abstract/conceptual)
        video_script: The full video script for context
        language: "id" for Indonesian, "en" for English
        enhancement_factor: How many additional visual queries per original term
        
    Returns:
        Enhanced list of search terms
    """
    if not original_terms:
        return original_terms
    
    enhanced = []
    
    for term in original_terms:
        # Add original term (may be abstract/conceptual)
        enhanced.append(term)
        
        # Add visual-enhanced version
        visual_queries = generate_visual_queries_from_text(
            term, 
            language, 
            max_queries=enhancement_factor
        )
        
        for vq in visual_queries:
            if vq and vq not in enhanced:
                enhanced.append(vq)
    
    return enhanced


# Integration function for backward compatibility
def generate_enhanced_search_terms(
    video_subject: str,
    video_script: str,
    original_terms: List[str],
    language: str = "id",
    mode: str = "enhance"
) -> List[str]:
    """
    Generate enhanced search terms using visual intelligence.
    
    This is the main integration point for the visual intelligence module.
    It can either:
    - "enhance": Add visual queries to original terms
    - "replace": Use only visual-derived queries
    - "prioritize": Keep originals first, then add visual variants
    
    Args:
        video_subject: The video topic/subject
        video_script: The generated video script
        original_terms: Terms from LLM generate_terms()
        language: "id" for Indonesian, "en" for English
        mode: "enhance", "replace", or "prioritize"
        
    Returns:
        Enhanced search terms list
    """
    if not original_terms:
        # Generate fresh if none provided
        original_terms = generate_visual_queries_from_text(
            video_subject, language, max_queries=5
        )
    
    # Generate visual queries from entire script
    visual_queries = []
    for sentence in re.split(r'[。！？\n]', video_script):
        sentence = sentence.strip()
        if len(sentence) > 10:  # Skip very short sentences
            queries = generate_visual_queries_from_text(
                sentence, language, max_queries=2
            )
            visual_queries.extend(queries)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_visual = []
    for q in visual_queries:
        key = q.lower()
        if key not in seen and len(key) > 3:
            seen.add(key)
            unique_visual.append(q)
    
    if mode == "enhance":
        # Add visual queries to original terms
        result = list(original_terms)
        for vq in unique_visual[:3]:
            if vq not in result:
                result.append(vq)
        return result
    
    elif mode == "prioritize":
        # Keep originals and add visual variants
        result = list(original_terms)
        for vq in unique_visual:
            if vq not in result:
                result.append(vq)
        return result
    
    elif mode == "replace":
        # Use visual queries as primary
        return unique_visual[:len(original_terms)] or original_terms
    
    return original_terms