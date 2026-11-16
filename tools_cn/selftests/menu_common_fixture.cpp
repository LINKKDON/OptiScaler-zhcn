// Minimal stand-in for upstream OptiScaler/menu/menu_common.cpp.
//
// This fixture exists only so the drift regression test in
// tools_cn/selftests/run_drift_selftest.py can exercise localize.py without
// cloning the 1.5 GB upstream tree. It is deliberately tiny, pure ASCII (just
// like the real file before localization) and carries exactly the two anchors
// apply_font() needs, one occurrence each:
//
//   1. the Hack_Compressed.h include (the one the CJK include is inserted after)
//   2. the OverlayMenu if-block (the one the merge block is inserted before)
//
// The literal anchor strings are NOT spelled out in this comment on purpose:
// the selftest asserts that each anchor occurs exactly once in the file, and a
// comment copy would make that count wrong. Keep the two code lines below
// byte-identical to what the real file has. If upstream renames either one,
// this fixture must be updated together with localize.py - the regression test
// is what forces that conversation to happen.

#include "pch.h"

#include <string>

#include "menu_common.h"
#include "font/Hack_Compressed.h"

void MenuCommon::loadFont()
{
    ImGuiIO& io = ImGui::GetIO();

    if (!Config::Instance()->OverlayMenu.value_or_default())
    {
        io.Fonts->AddFontFromMemoryCompressedTTF(hack_compressed_data,
                                                 hack_compressed_size, fontSize);
    }

    // A couple of menu strings so the dictionary pass has something to do.
    Labels.insert("Reprojection Settings");
    Labels.insert("opening ImGui");
}
