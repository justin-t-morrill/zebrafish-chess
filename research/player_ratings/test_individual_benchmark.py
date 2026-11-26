import unittest
import numpy as np
from individual_benchmark import paired_metrics, partitions, people, player_hash_partitions


class BenchmarkTests(unittest.TestCase):
    def test_shared_mean_cannot_pass_individual_separation(self):
        y = np.array([[1400,1800],[2100,1700],[1000,1100]],float)
        p = np.repeat(y.mean(1,keepdims=True),2,axis=1)
        m = paired_metrics(y,p)
        self.assertEqual(m['mean_rating_mae'],0)
        self.assertEqual(m['gap_mae'],m['zero_gap_mae'])
        self.assertEqual(m['higher_rated_accuracy'],.5)
        self.assertEqual(m['equal_rounded_fraction'],1)
        self.assertIsNone(m['gap_correlation'])

    def test_spreading_ratings_arbitrarily_can_make_gap_error_worse(self):
        y = np.array([[1500,1600],[1800,1500]],float)
        p = np.repeat(y.mean(1,keepdims=True),2,axis=1) + np.array([500,-500])
        self.assertGreater(paired_metrics(y,p)['gap_mae'],paired_metrics(y,p)['zero_gap_mae'])
        self.assertEqual(paired_metrics(y,p)['player_mae'],paired_metrics(y[:,::-1],p[:,::-1])['player_mae'])

    def test_both_players_purged_and_test_fixed(self):
        players = np.array([[f'w{i}',f'b{i}'] for i in range(600)])
        players[0,0] = players[500,1]
        train, valid, test = partitions(players,np.arange(600).astype(str),np.arange(500),np.arange(500,600))
        self.assertNotIn(0,train)
        self.assertNotIn(0,valid)
        self.assertEqual(test.tolist(),list(range(500,600)))
        for a,b in ((train,valid),(train,test),(valid,test)):
            self.assertFalse(people(players,a)&people(players,b))

    def test_player_first_assignment_is_stable_and_label_free(self):
        p=np.array([[f'p{i}',f'p{i+1}'] for i in range(3000)])
        split=player_hash_partitions(p,np.arange(len(p)))
        swapped=player_hash_partitions(p[:,::-1],np.arange(len(p)))
        for a,b in zip(split,swapped):
            self.assertEqual(a.tolist(),b.tolist())
        for a,b in ((split[0],split[1]),(split[0],split[2]),(split[1],split[2])):
            self.assertFalse(people(p,a)&people(p,b))


if __name__ == '__main__':
    unittest.main()
