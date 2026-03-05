import pytest

from app.compile_cache import CompileCache, CompileCacheEntry, build_compile_key


def test_build_compile_key_is_deterministic():
    key_one = build_compile_key(
        project_id="project-1",
        tex_content="abc",
        engine="pdflatex",
        flags="pdflatex:2:fallback-latexmk",
    )
    key_two = build_compile_key(
        project_id="project-1",
        tex_content="abc",
        engine="pdflatex",
        flags="pdflatex:2:fallback-latexmk",
    )
    assert key_one == key_two


def test_build_compile_key_changes_on_input_change():
    key_one = build_compile_key(
        project_id="project-1",
        tex_content="abc",
        engine="pdflatex",
        flags="pdflatex:2:fallback-latexmk",
    )
    key_two = build_compile_key(
        project_id="project-1",
        tex_content="abcd",
        engine="pdflatex",
        flags="pdflatex:2:fallback-latexmk",
    )
    assert key_one != key_two


@pytest.mark.asyncio
async def test_compile_cache_set_get_and_lru():
    cache = CompileCache(max_entries=2)
    first = CompileCacheEntry(
        key="k1",
        pdf_path="p1.pdf",
        project_id="project-1",
        engine="latexmk",
        flags="latexmk",
    )
    second = CompileCacheEntry(
        key="k2",
        pdf_path="p2.pdf",
        project_id="project-2",
        engine="latexmk",
        flags="latexmk",
    )
    third = CompileCacheEntry(
        key="k3",
        pdf_path="p3.pdf",
        project_id="project-3",
        engine="latexmk",
        flags="latexmk",
    )

    await cache.set(first)
    await cache.set(second)
    assert (await cache.get("k1")) is not None
    await cache.set(third)

    assert await cache.get("k2") is None
    assert (await cache.get("k1")) is not None
    assert (await cache.get("k3")) is not None


@pytest.mark.asyncio
async def test_compile_cache_invalidate_project():
    cache = CompileCache(max_entries=10)
    await cache.set(
        CompileCacheEntry(
            key="k1",
            pdf_path="p1.pdf",
            project_id="project-1",
            engine="latexmk",
            flags="latexmk",
        )
    )
    await cache.set(
        CompileCacheEntry(
            key="k2",
            pdf_path="p2.pdf",
            project_id="project-2",
            engine="latexmk",
            flags="latexmk",
        )
    )

    await cache.invalidate_project("project-1")
    assert await cache.get("k1") is None
    assert await cache.get("k2") is not None
