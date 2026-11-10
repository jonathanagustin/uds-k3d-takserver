// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import org.junit.jupiter.api.Test;

/** Run the same real compatibility contracts under PIT's JUnit test discovery. */
class MutationContractsTest {
    @Test void pairContract() throws Exception {
        PairCompatibilityTest.main(new String[0]);
    }

    @Test void cacheContract() throws Exception {
        cache.LruCacheCompatibilityTest.main(new String[0]);
    }
}
